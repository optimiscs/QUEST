#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_dir"
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
exec "$repo_dir/workspace/env/bin/python" -u "$repo_dir/inference/bm25_pool_service.py" \
  --workers "${QUEST_BM25_WORKERS:-64}" --queue-limit "${QUEST_BM25_QUEUE_LIMIT:-128}" \
  --port "${QUEST_BM25_PORT:-18215}"
