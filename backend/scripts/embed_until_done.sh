#!/usr/bin/env bash
# Resume in batches: past service cases first, then manual pages.
# Successful batches proceed immediately; failures cool down before retrying.
cd "$(dirname "$0")/.." || exit 1
# WSL/Linux uses its own environment, never the Windows .venv.
if [[ -n "${EMBEDDING_PYTHON:-}" ]]; then
  PY="$EMBEDDING_PYTHON"
elif [[ "$(uname -s)" == Linux* ]]; then
  PY=".venv_wsl/bin/python"
else
  PY=".venv/Scripts/python.exe"
fi
if [[ ! -x "$PY" ]]; then
  echo "Python environment missing: $PY" >&2
  exit 1
fi
export GEMINI_EMBEDDING_MAX_RETRIES="${GEMINI_EMBEDDING_MAX_RETRIES:-0}"
export PYTHONUTF8=1
# PROVIDER=gemini (daily quota, small cooldowns) or PROVIDER=qwen (local server, no quota). One loop per provider.
PROVIDER="${PROVIDER:-gemini}"
if [[ "$PROVIDER" != "gemini" && "$PROVIDER" != "qwen" ]]; then
  echo "PROVIDER must be gemini or qwen" >&2
  exit 1
fi
BATCH_SIZE="${BATCH_SIZE:-$([[ "$PROVIDER" == qwen ]] && echo 32 || echo 16)}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-0}"
PAUSE_SECONDS="${PAUSE_SECONDS:-60}"
# Items per Python run. Empty means one process works through everything pending (no per-batch start-up and
# pending-list cost); the gemini default stays one batch per run so a quota error cools down quickly.
RUN_LIMIT="${RUN_LIMIT-$([[ "$PROVIDER" == qwen ]] && echo '' || echo "$BATCH_SIZE")}"
for value in "$BATCH_SIZE" "$PAUSE_SECONDS"; do
  if ! [[ "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "Batch size and cooldown must be positive integers" >&2
    exit 1
  fi
done
if ! [[ "$INTERVAL_SECONDS" =~ ^[0-9]+$ ]]; then
  echo "INTERVAL_SECONDS must be a non-negative integer" >&2
  exit 1
fi
if (( BATCH_SIZE > 100 )); then
  echo "BATCH_SIZE must not exceed 100" >&2
  exit 1
fi
# Prevent duplicate copies launched from this WSL/Linux environment.
if command -v flock >/dev/null 2>&1; then
  exec 9>"${TMPDIR:-/tmp}/codyssey-embedding-$PROVIDER.lock"
  flock -n 9 || { echo "Embedding loop already running" >&2; exit 1; }
fi
trap 'echo "[$(date -Iseconds)] embedding loop stopped"; exit 130' INT TERM
echo "[$(date -Iseconds)] batch embedding: provider=$PROVIDER batch=$BATCH_SIZE interval=${INTERVAL_SECONDS}s cooldown=${PAUSE_SECONDS}s"
for only in cases pages; do
  while true; do
    # The limit applies to this invocation, not the whole job. Ready hashes are skipped.
    # No synthetic probe: each successful API call embeds actual pending content.
    if out=$("$PY" scripts/index_embeddings.py --provider "$PROVIDER" --only "$only" \
        --batch-size "$BATCH_SIZE" ${RUN_LIMIT:+--limit "$RUN_LIMIT"} 2>&1); then
      echo "[$(date -Iseconds)] $only: $out"
      if [[ "$out" =~ remaining=0([[:space:]]|$) ]]; then
        break
      fi
      sleep "$INTERVAL_SECONDS"
    else
      echo "[$(date -Iseconds)] $only: $out"
      echo "[$(date -Iseconds)] retrying in ${PAUSE_SECONDS}s"
      sleep "$PAUSE_SECONDS"
    fi
  done
done
echo "[$(date -Iseconds)] all embeddings ready (activation is a separate step)"
