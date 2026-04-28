#!/bin/sh
set -eu

OLLAMA_URL="${OLLAMA_URL:-http://ollama:11434}"
DEFAULT_MODEL="${DEFAULT_MODEL:-qwen2.5-coder:7b}"

echo "[ollama-init] waiting for Ollama at ${OLLAMA_URL}..."

for i in $(seq 1 120); do
  if OLLAMA_HOST="$OLLAMA_URL" ollama list >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "[ollama-init] pulling model: ${DEFAULT_MODEL}"
OLLAMA_HOST="$OLLAMA_URL" ollama pull "${DEFAULT_MODEL}"

echo "[ollama-init] installed models:"
OLLAMA_HOST="$OLLAMA_URL" ollama list

echo "[ollama-init] done" 