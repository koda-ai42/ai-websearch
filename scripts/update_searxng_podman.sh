#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONTAINER_NAME="ai-websearch-searxng"
IMAGE="${AI_WEBSEARCH_SEARXNG_IMAGE:-}"

if [[ "$IMAGE" != docker.io/searxng/searxng@sha256:* ]]; then
  printf '%s\n' \
    'Set AI_WEBSEARCH_SEARXNG_IMAGE to a reviewed docker.io/searxng/searxng@sha256:... reference.' >&2
  exit 1
fi

podman pull "$IMAGE" >/dev/null
if podman container exists "$CONTAINER_NAME"; then
  podman stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
  podman rm "$CONTAINER_NAME" >/dev/null
fi

AI_WEBSEARCH_SEARXNG_IMAGE="$IMAGE" "$ROOT/scripts/start_searxng_podman.sh"
