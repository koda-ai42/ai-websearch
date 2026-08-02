#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONTAINER_NAME="ai-websearch-searxng"
IMAGE="${AI_WEBSEARCH_SEARXNG_IMAGE:-docker.io/searxng/searxng@sha256:ec536bcd1e83577aad4cc07f7ecb9a30858a9a905d2d57c8796abc83f872a036}"

if [[ "$IMAGE" != docker.io/searxng/searxng@sha256:* ]]; then
  printf '%s\n' 'AI_WEBSEARCH_SEARXNG_IMAGE must be an official digest-pinned image.' >&2
  exit 1
fi

if podman container exists "$CONTAINER_NAME"; then
  podman start "$CONTAINER_NAME" >/dev/null
else
  if ! command -v openssl >/dev/null 2>&1; then
    printf '%s\n' 'openssl is required to create the local SearXNG secret.' >&2
    exit 1
  fi
  export SEARXNG_SECRET="$(openssl rand -hex 32)"
  podman run -d \
    --name "$CONTAINER_NAME" \
    --pull=missing \
    --security-opt=no-new-privileges \
    --env SEARXNG_SECRET \
    -p 127.0.0.1:8888:8080 \
    -v "$ROOT/searxng/settings.yml:/etc/searxng/settings.yml:ro,Z" \
    "$IMAGE" >/dev/null
  unset SEARXNG_SECRET
fi

printf '%s\n' 'SearXNG: http://127.0.0.1:8888'
