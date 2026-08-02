#!/usr/bin/env bash
set -euo pipefail
if distrobox list | grep -q 'ai-websearch'; then
  echo 'Distrobox ai-websearch already exists.'
  exit 0
fi
distrobox create --yes --name ai-websearch --image docker.io/library/ubuntu:26.04 --additional-packages "python3 python3-dev build-essential git curl ca-certificates libgl1 libglib2.0-0"
