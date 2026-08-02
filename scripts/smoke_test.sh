#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run python scripts/validate_package.py
uv run python tests/smoke.py
