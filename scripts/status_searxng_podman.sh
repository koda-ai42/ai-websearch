#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="ai-websearch-searxng"

if ! podman container exists "$CONTAINER_NAME"; then
  printf '%s\n' 'SearXNG container is not installed.'
  exit 1
fi

podman inspect \
  --format 'name={{.Name}} state={{.State.Status}} image={{.ImageName}}' \
  "$CONTAINER_NAME"
