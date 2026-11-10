#!/usr/bin/env bash
# Resume embedding until nothing is left: past service cases first, then manual pages.
# A cheap probe runs before each pass so an overloaded or rate-limiting gateway is not hammered with
# full batches; failed batches are retried by the next pass.
cd "$(dirname "$0")/.." || exit 1
PY=".venv/Scripts/python.exe"
export GEMINI_EMBEDDING_BACKOFF_SECONDS="${GEMINI_EMBEDDING_BACKOFF_SECONDS:-10}"
export GEMINI_EMBEDDING_MAX_BACKOFF_SECONDS="${GEMINI_EMBEDDING_MAX_BACKOFF_SECONDS:-120}"
export GEMINI_EMBEDDING_MAX_RETRIES="${GEMINI_EMBEDDING_MAX_RETRIES:-6}"
export PYTHONUTF8=1

probe() {
  "$PY" - <<'PY'
import sys
from dotenv import load_dotenv
load_dotenv(".env")
from app.agent_rag.embedding import EmbeddingUnavailable, GeminiEmbedder
embedder = GeminiEmbedder.from_env()
embedder.retries = 0
try:
    embedder.embed_documents(["probe"])
except EmbeddingUnavailable as exc:
    print(f"gateway not ready: {exc.category} {exc.http_status}")
    sys.exit(1)
PY
}

for only in cases pages; do
  while true; do
    until probe; do sleep "${PAUSE_SECONDS:-120}"; done
    "$PY" scripts/index_embeddings.py --only "$only" --batch-size "${BATCH_SIZE:-16}" && break
    echo "[$(date +%T)] $only: not finished, retrying in ${PAUSE_SECONDS:-120}s"
    sleep "${PAUSE_SECONDS:-120}"
  done
done
echo "[$(date +%T)] all embeddings ready"
