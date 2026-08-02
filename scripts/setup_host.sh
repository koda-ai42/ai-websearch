#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' 'uv is required. Run ./scripts/install_uv.sh first.' >&2
  exit 1
fi

uv sync --frozen
uv run crawl4ai-setup
printf '%s\n' 'Host Python environment and ephemeral Chromium runtime are ready.'
