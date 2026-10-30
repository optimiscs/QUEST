#!/usr/bin/env bash
set -eu
cd /root/autodl-tmp/Quest
export CUDA_HOME=/usr/local/cuda
export PATH="/root/autodl-tmp/Quest/workspace/env/bin:/usr/local/cuda/bin:$PATH"
export TOKENIZERS_PARALLELISM=false
run=workspace/strict-reproduction/gaia-bm25-5gpu-base-20261029-r1
wait_health() {
  local port="$1" i
  for ((i=0;i<180;i++)); do
    if curl -fsS --max-time 2 "http://127.0.0.1:$port/v1/models" >/dev/null; then return 0; fi
    sleep 5
  done
  echo "Service $port failed to start within 15 minutes" >&2
  return 1
}
wait_health 18210
for pair in '1 18201' '2 18202' '3 18203' '4 18204'; do
  read -r gpu port <<< "$pair"
  CUDA_VISIBLE_DEVICES="$gpu" setsid -f workspace/env/bin/vllm serve workspace/models/Qwen3.5-4B --served-model-name QWEN35-BASE --host 127.0.0.1 --port "$port" --language-model-only --tensor-parallel-size 1 --dtype bfloat16 --max-model-len 65536 --max-num-seqs 8 --gpu-memory-utilization 0.92 --disable-custom-all-reduce >> "$run/server-logs/gpu$gpu.log" 2>&1 < /dev/null
  echo "Started GPU $gpu on port $port"
done
for port in 18201 18202 18203 18204; do wait_health "$port"; done
echo 'All five endpoints are healthy.'
