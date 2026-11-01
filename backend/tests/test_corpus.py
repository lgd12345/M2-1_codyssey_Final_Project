import hashlib
import json

import pytest

from app.agent_rag.corpus import infer_machine, load_manifest


def test_manifest_verifies_pdf_hash_and_prepares_each_page(tmp_path):
    pdf = b"synthetic-pdf"
    digest = hashlib.sha256(pdf).hexdigest()
    (tmp_path / "sample.pdf").write_bytes(pdf)
    (tmp_path / "sample.chunks.jsonl").write_text("\n".join([
        json.dumps({"source_sha256": digest, "pdf_page": 1, "printed_page": "1", "page_class": "text", "text": "서보모터가\x00 과열", "verification": "verified"}),
        json.dumps({"source_sha256": digest, "pdf_page": 2, "page_class": "exploded_drawing", "text": "> **Text in image (OCR, unverified):** bad OCR", "verification": "needs_review"}),
    ]), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({"schema_version": 1, "documents": [
        {"source_sha256": digest, "source_path": "/raw_files/F400/1. FANUC/Manual.pdf",
         "title": "Manual", "pdf_file": "sample.pdf", "chunks_file": "sample.chunks.jsonl", "page_count": 2},
        {"source_sha256": digest, "source_path": "/raw_files/F400/copy/Manual.pdf",
         "title": "duplicate", "pdf_file": "sample.pdf", "chunks_file": "sample.chunks.jsonl", "page_count": 2},
    ]}), encoding="utf-8")

    documents = load_manifest(tmp_path)
    assert len(documents) == 1
    assert set(documents[0].aliases) == {
        "/raw_files/F400/1. FANUC/Manual.pdf", "/raw_files/F400/copy/Manual.pdf"
    }
    assert documents[0].machine == "F400"
    assert documents[0].manufacturer == "FANUC"
    assert documents[0].pages[0].content == "서보모터가 과열"
    assert documents[0].pages[1].content == ""
    assert documents[0].pages[1].verification == "needs_review"


def test_manifest_rejects_chunk_rows_from_a_different_source_hash(tmp_path):
    pdf = b"synthetic-pdf"
    digest = hashlib.sha256(pdf).hexdigest()
    (tmp_path / "sample.pdf").write_bytes(pdf)
    (tmp_path / "sample.chunks.jsonl").write_text(json.dumps({
        "source_sha256": "f" * 64, "pdf_page": 1, "page_class": "text", "text": "wrong source"
    }), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({"schema_version": 1, "documents": [
        {"source_sha256": digest, "source_path": "/raw_files/F400/Manual.pdf",
         "pdf_file": "sample.pdf", "chunks_file": "sample.chunks.jsonl", "page_count": 1},
    ]}), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid chunks line"):
        load_manifest(tmp_path)


def test_machine_scope_prefers_specific_machine_folder_when_present():
    assert infer_machine("/raw_files/F400/F400_500_650VM/4. Parts list/item.pdf") == "F400_500_650VM"
    assert infer_machine("/raw_files/F510B/1. FANUC/manual.pdf") == "F510B"
    assert infer_machine("/raw_files/F400 (2)/1. FANUC/manual.pdf") == "F400"


def test_manifest_rejects_pdf_hash_mismatch(tmp_path):
    (tmp_path / "sample.pdf").write_bytes(b"wrong")
    (tmp_path / "sample.chunks.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({"schema_version": 1, "documents": [
        {"source_sha256": "a" * 64, "source_path": "/raw_files/F400/Manual.pdf",
         "pdf_file": "sample.pdf", "chunks_file": "sample.chunks.jsonl", "page_count": 0},
    ]}), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256"):
        load_manifest(tmp_path)
