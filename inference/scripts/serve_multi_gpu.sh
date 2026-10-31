#!/usr/bin/env bash
# One independent vLLM replica per GPU. Runs in foreground until stopped.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SINGLE="$ROOT/inference/scripts/serve_single_gpu.sh"
usage() { echo 'Usage: serve_multi_gpu.sh [--dry-run] MODEL:GPU[,GPU...]:BASE_PORT [...]'; echo 'Example: serve_multi_gpu.sh 27b:0,1,2:19000 reranker:3:19003'; }
dry=; if [[ ${1:-} == --dry-run ]]; then dry=--dry-run; shift; fi
[[ $# -gt 0 ]] || { usage >&2; exit 2; }
declare -A seen_gpu=() seen_port=()
declare -a models=() gpus=() ports=() pids=()
for group in "$@"; do
  IFS=: read -r model ids base extra <<< "$group"
  [[ -z ${extra:-} && $model =~ ^(27b|swift-27b|4b|4b-sft|embedding|reranker)$ && ${base:-} =~ ^[0-9]+$ && ${ids:-} =~ ^[0-9]+(,[0-9]+)*$ ]] || { echo "Invalid group: $group" >&2; usage >&2; exit 2; }
  IFS=, read -ra group_gpus <<< "$ids"
  for i in "${!group_gpus[@]}"; do
    gpu=$((10#${group_gpus[$i]})); port=$((10#$base+i))
    ((port >= 1 && port <= 65535)) || { echo "Invalid port: $port" >&2; exit 2; }
    [[ ! ${seen_gpu[$gpu]+set} && ! ${seen_port[$port]+set} ]] || { echo "Repeated GPU or port: $gpu / $port" >&2; exit 2; }
    seen_gpu[$gpu]=1; seen_port[$port]=1; models+=("$model"); gpus+=("$gpu"); ports+=("$port")
  done
done
for i in "${!models[@]}"; do "$SINGLE" "${models[$i]}" "${gpus[$i]}" "${ports[$i]}" --dry-run >/dev/null; done
if [[ $dry == --dry-run ]]; then
  for i in "${!models[@]}"; do "$SINGLE" "${models[$i]}" "${gpus[$i]}" "${ports[$i]}" --dry-run; done
  exit 0
fi
# Fail before launching anything if a GPU does not exist or a port is already bound.
"$ROOT/workspace/env/bin/python" - "${gpus[*]}" "${ports[*]}" <<'PY'
import socket, subprocess, sys
ids = set(subprocess.check_output(['nvidia-smi', '--query-gpu=index', '--format=csv,noheader,nounits'], text=True).split())
for gpu in sys.argv[1].split():
    if gpu not in ids: raise SystemExit(f'GPU {gpu} does not exist')
for port in map(int, sys.argv[2].split()):
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try: s.bind(('127.0.0.1', port))
        except OSError as e: raise SystemExit(f'Port {port} unavailable: {e}')
PY
log_dir=${QUEST_VLLM_LOG_DIR:-"$ROOT/workspace/vllm-multi-logs/$(date +%Y%m%d-%H%M%S)-$$"}
mkdir -p "$log_dir"
cleanup() { trap - EXIT INT TERM; ((${#pids[@]})) && kill "${pids[@]}" 2>/dev/null || true; wait 2>/dev/null || true; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
for i in "${!models[@]}"; do
  log="$log_dir/${models[$i]}-gpu${gpus[$i]}-port${ports[$i]}.log"
  "$SINGLE" "${models[$i]}" "${gpus[$i]}" "${ports[$i]}" >"$log" 2>&1 &
  pids+=("$!")
  printf 'model=%s gpu=%s port=%s pid=%s log=%s\n' "${models[$i]}" "${gpus[$i]}" "${ports[$i]}" "$!" "$log"
done
printf 'Services are starting. Check each /health and log before sending requests. Ctrl-C stops all.\n'
set +e
wait -n "${pids[@]}"
status=$?
set -e
printf 'A service exited with status %s; stopping the group.\n' "$status" >&2
exit "$status"
