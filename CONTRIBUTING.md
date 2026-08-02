# Contributing

Use `uv`; do not add pip, Docker, Docker Compose, or a llama.cpp embedding server workflow. Read `AGENTS.md` before changing retrieval or crawl behavior.

For production behavior changes:

1. Add or update an offline benchmark and record the before/after accuracy, reliability, and latency effects separately.
2. Add unit tests, keeping mocked and live integration coverage clearly labeled.
3. Run `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy src
   tests`, `uv run python -m compileall src tests`, `uv run pytest -q -m 'not
   live'`, `bash -n scripts/*.sh`, and
   `UV_CACHE_DIR=/tmp/ai-websearch-uv-cache ./scripts/smoke_test.sh`.
4. Document live integrations that were not actually executed.

Keep changes small by separating ranking, crawling, caching, and chunking work where practical. Preserve MCP tool compatibility unless the change explicitly requires a new optional parameter.
