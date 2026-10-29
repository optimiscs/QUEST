#!/bin/bash
set -euo pipefail
gpu=${1:?GPU index required}
port=${2:?port required}
cd /root/autodl-tmp/Quest/workspace
export HF_HOME="$PWD/cache/huggingface" TMPDIR="$PWD/tmp" TORCHINDUCTOR_CACHE_DIR="$PWD/cache/torchinductor"
export CUDA_VISIBLE_DEVICES="$gpu" VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1 VLLM_USE_FLASHINFER_SAMPLER=0
export XDG_CACHE_HOME="$PWD/cache/xdg" CUDA_HOME="$PWD/env/lib/python3.12/site-packages/nvidia/cu13"
export PATH="$CUDA_HOME/bin:$PWD/env/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export NCCL_P2P_DISABLE=1 NCCL_IB_DISABLE=1
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
exec ./env/bin/vllm serve "$PWD/models/Qwen3.5-4B" --served-model-name QWEN35-BASE --host 127.0.0.1 --port "$port" --language-model-only --tensor-parallel-size 1 --dtype bfloat16 --max-model-len 65536 --max-num-seqs 8 --gpu-memory-utilization 0.92 --disable-custom-all-reduce --enable-lora --max-lora-rank 16 --lora-modules QWEN35-SFT10="$PWD/sft-runs/quest4b-v095-four32g-qlora64k-10pct-final"
