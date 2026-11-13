from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterator

from app.agent_rag.preprocess import prepare_page_text, stable_content_hash


@dataclass(frozen=True)
class CorpusPage:
    pdf_page: int
    printed_page: str | None
    page_class: str
    content: str
    content_hash: str
    verification: str
    route: str | None
    flags: tuple[str, ...]


@dataclass(frozen=True)
class CorpusDocument:
    sha256: str
    title: str
    source_path: str
    aliases: tuple[str, ...]
    pdf_path: Path
    page_count: int
    machine: str
    manufacturer: str
    pages: tuple[CorpusPage, ...]


def infer_machine(source_path: str) -> str:
    parts = [part for part in source_path.replace("\\", "/").split("/") if part]
    try:
        index = parts.index("raw_files")
        candidates = parts[index + 1:index + 3]
        machine_candidates = [part for part in candidates if re.match(r"^F\d", part, re.IGNORECASE)]
        machine = machine_candidates[-1] if machine_candidates else (candidates[0] if candidates else "unknown")
        return re.sub(r"\s+\(\d+\)$", "", machine).strip()
    except ValueError:
        return parts[0] if parts else "unknown"


def infer_manufacturer(source_path: str) -> str:
    normalized = source_path.casefold()
    if "fanuc" in normalized:
        return "FANUC"
    if "hyundai" in normalized or "wia" in normalized:
        return "HYUNDAI WIA"
    return "unknown"


def load_manifest(corpus_dir: str | Path, *, verify_pdf_hash: bool = True) -> list[CorpusDocument]:
    root = Path(corpus_dir).resolve()
    manifest_path = root / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("documents"), list):
        raise ValueError("unsupported corpus manifest")
    documents: list[CorpusDocument] = []
    seen: dict[str, int] = {}
    for item in payload["documents"]:
        digest = str(item["source_sha256"]).lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("invalid source SHA-256")
        pdf_path = (root / item["pdf_file"]).resolve()
        chunks_path = (root / item["chunks_file"]).resolve()
        if root not in pdf_path.parents or root not in chunks_path.parents:
            raise ValueError("manifest path escapes corpus directory")
        if not pdf_path.is_file() or not chunks_path.is_file():
            raise ValueError("corpus artifact is missing")
        if verify_pdf_hash and file_sha256(pdf_path) != digest:
            raise ValueError("PDF SHA-256 does not match manifest")
        source_path = str(item.get("source_path", ""))
        aliases = tuple(dict.fromkeys(path for path in
                                      (source_path, *map(str, item.get("aliases", []))) if path))
        declared_page_count = int(item["page_count"]) if item.get("page_count") is not None else None
        if digest in seen:
            existing_index = seen[digest]
            existing = documents[existing_index]
            if declared_page_count is not None and declared_page_count != existing.page_count:
                raise ValueError("duplicate source SHA-256 has inconsistent page counts")
            documents[existing_index] = replace(
                existing, aliases=tuple(dict.fromkeys((*existing.aliases, *aliases)))
            )
            continue
        seen[digest] = len(documents)
        pages: list[CorpusPage] = []
        with chunks_path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    row: dict[str, Any] = json.loads(line)
                    if str(row.get("source_sha256", "")).lower() != digest:
                        raise ValueError("chunk source SHA-256 does not match manifest")
                    page_number = int(row["pdf_page"])
                    if page_number < 1:
                        raise ValueError("PDF page number must be positive")
                    page_class = str(row.get("page_class", "text"))
                    content = prepare_page_text(str(row.get("text", "")), page_class=page_class)
                    pages.append(CorpusPage(
                        pdf_page=page_number,
                        printed_page=str(row["printed_page"]) if row.get("printed_page") not in (None, "") else None,
                        page_class=page_class,
                        content=content,
                        content_hash=stable_content_hash(content),
                        verification=str(row.get("verification", "needs_review")),
                        route=str(row.get("route")) if row.get("route") else None,
                        flags=tuple(map(str, row.get("flags", []))),
                    ))
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(f"invalid chunks line {line_number} in {chunks_path.name}") from exc
        if len({page.pdf_page for page in pages}) != len(pages):
            raise ValueError("duplicate PDF page number in document")
        if declared_page_count is None:
            declared_page_count = len(pages)
        if any(page.pdf_page > declared_page_count for page in pages):
            raise ValueError("chunk page number exceeds manifest page count")
        title = str(item.get("title") or Path(source_path).stem or digest[:12])
        documents.append(CorpusDocument(
            sha256=digest, title=title, source_path=source_path, aliases=aliases,
            pdf_path=pdf_path, page_count=declared_page_count,
            machine=str(item.get("machine") or infer_machine(source_path)),
            manufacturer=str(item.get("manufacturer") or infer_manufacturer(source_path)),
            pages=tuple(sorted(pages, key=lambda page: page.pdf_page)),
        ))
    return documents


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def iter_documents(corpus_dir: str | Path) -> Iterator[CorpusDocument]:
    yield from load_manifest(corpus_dir)
