#!/usr/bin/env bash
set -euo pipefail

if podman container exists ai-websearch-searxng; then
  podman stop ai-websearch-searxng >/dev/null
fi
