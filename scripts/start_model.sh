#!/usr/bin/env bash
# Serve Sentinel V6 (Llama-3.1-8B-Instruct + LoRA checkpoint-512) with vLLM.
# Localhost only. Base weights and adapter are mounted read-only. Offline.
# Cold start ~57 s (measured Sept 23): eager safetensors load (10 s vs 111 s
# with mmap on GB10 unified memory) + --enforce-eager (no torch.compile or
# CUDA-graph capture; same ~420 ms verdict latency, no compile cache to lose).
# --init: vLLM as PID 1 ignored SIGTERM, so every stop waited 20 s for SIGKILL.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="${BTG_VLLM_IMAGE:-nvcr.io/nvidia/vllm:25.11-py3}"
NAME=btg-sentinel

docker rm -f "$NAME" >/dev/null 2>&1 || true

exec docker run --name "$NAME" --rm --init \
  --gpus all --ipc=host \
  -p 127.0.0.1:8001:8000 \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 -e VLLM_NO_USAGE_STATS=1 \
  -e DO_NOT_TRACK=1 -e HF_HUB_DISABLE_TELEMETRY=1 -e HF_DATASETS_OFFLINE=1 \
  -v "$HOME/.cache/huggingface:/root/.cache/huggingface:ro" \
  -v "$ROOT/models/sentinel-v6-ckpt512:/models/sentinel-v6:ro" \
  "$IMAGE" \
  vllm serve meta-llama/Llama-3.1-8B-Instruct \
    --host 0.0.0.0 --port 8000 \
    --dtype bfloat16 \
    --safetensors-load-strategy eager \
    --enforce-eager \
    --enable-lora --max-lora-rank 8 --max-loras 1 \
    --lora-modules sentinel-v6=/models/sentinel-v6 \
    --max-model-len 2048 \
    --max-num-seqs 8 \
    --gpu-memory-utilization 0.30 \
    --enable-prefix-caching
