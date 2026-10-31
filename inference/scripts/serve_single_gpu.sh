#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
usage() { echo 'Usage: serve_single_gpu.sh {27b|swift-27b|4b|4b-sft|embedding|reranker} GPU PORT [--dry-run]'; }
if [[ $# -lt 3 || $# -gt 4 ]]; then usage >&2; exit 2; fi
kind=$1; gpu=$2; port=$3; dry=${4:-}
[[ $gpu =~ ^[0-9]+$ && $port =~ ^[0-9]+$ && $port -ge 1 && $port -le 65535 ]] || { usage >&2; exit 2; }
[[ -z $dry || $dry == --dry-run ]] || { usage >&2; exit 2; }
VENV="$ROOT/workspace/env"; MODELS="$ROOT/workspace/models"
export CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES="$gpu" TOKENIZERS_PARALLELISM=false
export CUDA_HOME="$VENV/lib/python3.12/site-packages/nvidia/cu13"
export PATH="$CUDA_HOME/bin:$VENV/bin:$PATH"
export VLLM_USE_FLASHINFER_SAMPLER="${VLLM_USE_FLASHINFER_SAMPLER:-0}"
cmd=("$VENV/bin/vllm" serve)
case "$kind" in
  27b) model="$MODELS/Qwen3.8-27B-NVFP4"; name=QWEN38-27B-NVFP4 ;;
  swift-27b) model="$MODELS/Swift-1.5-Qwen3.8-27b-W4A16-AWQ-mtp-fix"; name=SWIFT-1.5-27B-AWQ ;;
  4b|4b-sft) model="$MODELS/Qwen3.5-4B"; name=QWEN35-BASE ;;
  reranker) model="$MODELS/Qwen3-Reranker-8B"; name=QWEN3-RERANKER-8B ;;
  embedding) model="$MODELS/Qwen3-Embedding-8B"; name=QWEN3-EMBEDDING-8B ;;
  *) usage >&2; exit 2 ;;
esac
[[ -d $model ]] || { echo "Model not found: $model" >&2; exit 1; }
cmd+=("$model" --served-model-name "$name" --host 127.0.0.1 --port "$port" --tensor-parallel-size 1 --dtype bfloat16 --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION:-0.92}")
if [[ $kind == embedding ]]; then
  cmd+=(--runner pooling --max-model-len "${MAX_MODEL_LEN:-2048}" --max-num-seqs "${MAX_NUM_SEQS:-16}")
elif [[ $kind == reranker ]]; then
  # Rerankers are pooling models, not autoregressive generators; MTP does not apply.
  cmd+=(--runner pooling --convert classify --hf-overrides '{"architectures":["Qwen3ForSequenceClassification"],"classifier_from_token":["no","yes"],"is_original_qwen3_reranker":true}' --chat-template "$ROOT/inference/qwen3_reranker.jinja" --max-model-len "${MAX_MODEL_LEN:-2048}" --max-num-seqs "${MAX_NUM_SEQS:-16}")
else
  cmd+=(--language-model-only --enable-prompt-tokens-details --enable-per-request-metrics --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3 --tool-strict-level parameter --max-model-len "${MAX_MODEL_LEN:-65536}" --max-num-seqs "${MAX_NUM_SEQS:-8}" --attention-backend TRITON_ATTN --disable-custom-all-reduce --speculative-config "{\"method\":\"mtp\",\"num_speculative_tokens\":${MTP_TOKENS:-3}}")
  if [[ ${QUEST_VLLM_DISABLE_THINKING:-0} == 1 ]]; then
    cmd+=(--default-chat-template-kwargs '{"enable_thinking":false}')
  fi
  if [[ -n ${KV_CACHE_DTYPE:-} ]]; then cmd+=(--kv-cache-dtype "$KV_CACHE_DTYPE"); fi
  if [[ -n ${KV_OFFLOADING_SIZE:-} ]]; then
    cmd+=(--kv-offloading-size "$KV_OFFLOADING_SIZE" --kv-offloading-backend native)
  fi
  if [[ $kind == 4b-sft ]]; then
    adapter="$ROOT/workspace/sft-runs/quest4b-v095-four32g-qlora64k-10pct-final"
    [[ -d $adapter ]] || { echo "LoRA adapter not found: $adapter" >&2; exit 1; }
    cmd+=(--enable-lora --max-lora-rank 16 --lora-modules "QWEN35-SFT10=$adapter")
  fi
fi
# CUDA graphs use vLLM's default compilation configuration: do not pass --enforce-eager.
if [[ $dry == --dry-run ]]; then printf 'CUDA_VISIBLE_DEVICES=%q ' "$CUDA_VISIBLE_DEVICES"; printf '%q ' "${cmd[@]}"; printf '\n'; else exec "${cmd[@]}"; fi
