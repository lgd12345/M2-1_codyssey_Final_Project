"""Apply an explicitly reviewed embedding-input manifest; never modifies source pages or ready vectors.

Manifest: {"provider":"qwen", "inputs":[{"content_hash":..., "content":..., "review":{...}}]}.
Use --apply to persist after inspecting the dry run. Config-scoped, so other models are untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
from app.agent_rag.db import connect_database
from app.agent_rag.embedding import configured_embedder
from app.agent_rag.embedding_index import ensure_embedding_config
from app.agent_rag.settings import AgentSettings
from app.agent_rag.preprocess import stable_content_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    load_dotenv()
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    embedder = configured_embedder(provider=data["provider"])
    connection = connect_database(AgentSettings.from_env().database_url)
    try:
        cfg = ensure_embedding_config(connection, embedder)
        for item in data["inputs"]:
            digest, text, review = item["content_hash"], item["content"], item["review"]
            originals = connection.execute("SELECT DISTINCT content FROM rag_page WHERE content_hash=%s", (digest,)).fetchall()
            if len(originals) != 1 or stable_content_hash(originals[0][0]) != digest:
                raise ValueError("source hash not found or not matching")
            if not text.strip() or not review.get("pdf_checked"):
                raise ValueError("nonempty text and explicit PDF review are required")
            ready = connection.execute("SELECT status FROM rag_embedding WHERE config_id=%s AND content_hash=%s", (cfg, digest)).fetchone()
            if ready and ready[0] == "ready":
                raise ValueError("refusing to change input for an already-ready vector")
            print(digest, len(originals[0][0]), "->", len(text), "chars")
            if args.apply:
                connection.execute("""INSERT INTO rag_embedding_input_override
                    (config_id,content_hash,content,input_sha256,review) VALUES (%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT(config_id,content_hash) DO UPDATE SET content=EXCLUDED.content,
                    input_sha256=EXCLUDED.input_sha256,review=EXCLUDED.review""",
                    (cfg, digest, text, hashlib.sha256(text.encode()).hexdigest(), json.dumps(review)))
        if args.apply:
            connection.commit()
        else:
            connection.rollback()
    finally:
        connection.close()


if __name__ == "__main__":
    main()
