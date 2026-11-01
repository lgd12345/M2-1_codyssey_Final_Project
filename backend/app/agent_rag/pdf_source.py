from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Callable

from app.agent_rag.corpus import file_sha256
from app.agent_rag.preprocess import normalize_text


_RENDERER_CACHE_VERSION = "pdfium-render-v1"


@dataclass(frozen=True)
class SourcePage:
    document_sha256: str
    pdf_page: int
    printed_page: str | None
    title: str
    converted_text: str
    verification: str
    page_class: str
    pdf_text: str
    image_png: bytes
    asset_id: str


def render_pdf_page(pdf_path: str | Path, document_sha256: str, page_number: int, dpi: int, *,
                    cache_dir: str | Path | None = None,
                    renderer: Callable[[Path, int, int], bytes] | None = None) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{64}", document_sha256):
        raise ValueError("invalid PDF SHA-256")
    if page_number < 1:
        raise ValueError("page number must be positive")
    if not 72 <= dpi <= 300:
        raise ValueError("render DPI must be between 72 and 300")
    source = Path(pdf_path).resolve()
    if not source.is_file():
        raise FileNotFoundError("source PDF is missing")
    if cache_dir is None:
        from app.agent_rag.settings import AgentSettings
        root = AgentSettings.from_env().pdf_render_cache_dir.resolve()
    else:
        root = Path(cache_dir).resolve()
    version = _RENDERER_CACHE_VERSION
    key = hashlib.sha256(json.dumps([document_sha256, page_number, dpi, version]).encode()).hexdigest()
    target = root / document_sha256[:2] / f"{key}.png"
    if target.is_file():
        return target.read_bytes()
    image = renderer(source, page_number, dpi) if renderer else _render_with_pdfium(source, page_number, dpi)
    if not isinstance(image, bytes) or not image:
        raise ValueError("PDF renderer returned an empty image")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".render-", suffix=".tmp", delete=False) as temp:
        temp.write(image)
        temp_path = Path(temp.name)
    try:
        os.replace(temp_path, target)
    finally:
        temp_path.unlink(missing_ok=True)
    return image


def _render_with_pdfium(pdf_path: Path, page_number: int, dpi: int) -> bytes:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(pdf_path))
    try:
        if page_number > len(document):
            raise ValueError("page number exceeds source PDF page count")
        page = document[page_number - 1]
        try:
            bitmap = page.render(scale=dpi / 72)
            image = bitmap.to_pil().convert("RGB")
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=True)
            return output.getvalue()
        finally:
            page.close()
    finally:
        document.close()


def extract_pdf_text(pdf_path: str | Path, page_number: int) -> str:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(pdf_path))
    try:
        if page_number < 1 or page_number > len(document):
            raise ValueError("page number exceeds source PDF page count")
        page = document[page_number - 1]
        try:
            return normalize_text(page.get_textpage().get_text_range())
        finally:
            page.close()
    finally:
        document.close()


def open_source_page(document_sha256: str, page_number: int, *, asset_registry,
                     database_url: str | None = None, dpi: int | None = None, connect=None) -> SourcePage:
    from app.agent_rag.db import connect_database

    connection = (connect or connect_database)(database_url)
    try:
        row = connection.execute(
            """SELECT d.pdf_path,d.title,p.printed_page,p.content,p.verification,p.page_class
               FROM rag_document d JOIN rag_page p USING(source_sha256)
               WHERE d.source_sha256=%s AND p.pdf_page=%s""",
            (document_sha256, page_number),
        ).fetchone()
    finally:
        connection.close()
    if not row:
        raise LookupError("source document page was not found")
    pdf_path, title, printed_page, converted_text, verification, page_class = row
    if file_sha256(pdf_path) != document_sha256:
        raise ValueError("source PDF SHA-256 no longer matches the indexed document")
    page_dpi = dpi or int(os.getenv("PDF_RENDER_DPI", "150"))
    image = render_pdf_page(pdf_path, document_sha256, page_number, page_dpi)
    pdf_text = extract_pdf_text(pdf_path, page_number)
    asset_id = asset_registry.register(image, document_sha256=document_sha256, pdf_page=page_number)
    return SourcePage(document_sha256, page_number, printed_page, title, converted_text,
                      verification, page_class, pdf_text, image, asset_id)
