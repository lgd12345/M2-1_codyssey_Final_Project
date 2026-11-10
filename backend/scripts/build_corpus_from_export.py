"""Build a corpus directory (manifest.json + <sha>.chunks.jsonl + pdf/<sha>.pdf) from a
PDF->Markdown export zip and the zip holding the original PDFs.

The original PDFs are matched to export documents by SHA-256, so the manifest satisfies the
checks in app.agent_rag.corpus.load_manifest without relaxing them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import PurePosixPath
import shutil
import sys
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent_rag.corpus import load_manifest


def _sha256_of(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    digest = hashlib.sha256()
    with archive.open(info) as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build(export_zip: Path, raw_zip: Path, out: Path) -> dict[str, int]:
    out.mkdir(parents=True, exist_ok=True)
    (out / "pdf").mkdir(exist_ok=True)
    with zipfile.ZipFile(export_zip) as export, zipfile.ZipFile(raw_zip) as raw:
        docs: dict[str, dict] = {}
        for name in export.namelist():
            if name.endswith("/manifest.json"):
                folder = name.rsplit("/", 1)[0]
                sha = json.loads(export.read(name))["source_sha256"].lower()
                conversion = json.loads(export.read(f"{folder}/conversion.json"))
                if not conversion.get("complete"):
                    raise SystemExit(f"incomplete conversion: {folder}")
                docs[sha] = {"folder": folder, "pages": int(conversion["pages"])}

        paths: dict[str, list[zipfile.ZipInfo]] = {}
        for info in raw.infolist():
            if info.filename.lower().endswith(".pdf"):
                paths.setdefault(_sha256_of(raw, info), []).append(info)

        missing = sorted(set(docs) - set(paths))
        if missing:
            raise SystemExit(f"{len(missing)} export documents have no matching original PDF")

        documents = []
        for sha, meta in sorted(docs.items(), key=lambda item: item[1]["folder"]):
            sources = sorted(paths[sha], key=lambda info: info.filename)
            primary = sources[0].filename
            target_pdf = out / "pdf" / f"{sha}.pdf"
            if not target_pdf.is_file():
                with raw.open(sources[0]) as src, target_pdf.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
            chunks_name = f"{sha}.chunks.jsonl"
            (out / chunks_name).write_bytes(export.read(f"{meta['folder']}/chunks.jsonl"))
            aliases = [f"/raw_files/{info.filename}" for info in sources]
            documents.append({
                "source_sha256": sha,
                "source_path": aliases[0],
                "pdf_file": f"pdf/{sha}.pdf",
                "chunks_file": chunks_name,
                "title": PurePosixPath(primary).stem,
                "page_count": meta["pages"],
                "aliases": aliases,
            })
    (out / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "documents": documents}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return {"documents": len(documents), "unconverted_pdfs": len(paths) - len(documents)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-zip", required=True, type=Path)
    parser.add_argument("--raw-zip", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--no-validate", action="store_true")
    args = parser.parse_args()
    summary = build(args.export_zip, args.raw_zip, args.out)
    print(f"Built {summary['documents']} documents; "
          f"{summary['unconverted_pdfs']} original PDFs are not in the export.")
    if not args.no_validate:
        loaded = load_manifest(args.out)  # also verifies each PDF SHA-256
        print(f"Validated: {len(loaded)} documents, {sum(len(d.pages) for d in loaded)} pages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
