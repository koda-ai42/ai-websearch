# Validation

Package version: 0.1.0b1 (0.1.0 beta).

## Required offline checks

```bash
uv run python -m compileall src tests
uv run python -m pytest -q -m 'not live'
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
bash -n scripts/*.sh
UV_CACHE_DIR=/tmp/ai-websearch-uv-cache ./scripts/smoke_test.sh
uv run python -m benchmarks --all
uv build --no-sources
uv run python scripts/check_release.py --artifacts dist
```

The offline suite covers safe FTS syntax and BM25 direction against real SQLite FTS5, rank fusion, freshness, section-aware chunking, consent cleanup, pre-reranker filtering, answer-transaction compliance, agent classification/escalation and request-wide mode limits, schema migration, active-version cache semantics, access-wall classification, per-domain pacing, URL policy, CLI behavior, exact token packing with mocks, and reranker mode/error behavior.

## Manual live matrix

Run these separately and record the environment/date:

1. `./scripts/start_searxng_podman.sh`, then `uv run ai-websearch doctor --search-probe`.
2. `uv run ai-websearch searxng engines list --all`, toggle a disposable engine override, restart, and verify the live state.
3. Crawl one public static page, one JavaScript page, and synthetic consent/authentication/CAPTCHA/subscription/access-denied pages.
4. Verify a failed refresh does not replace known-good cached evidence.
5. Start a real `llama-server`; verify auto and manual discovery, `/props`, exact `/tokenize`, and WebUI MCP rendering of clickable citations.
6. Run CrossEncoder inference on CPU and any intended GPU, recording startup latency, query latency, and peak memory.
7. Verify a synthetic CAPTCHA is classified as terminal, is not retried or cached, and never opens a visible browser. Do not solve or bypass real third-party challenges.

Do not claim any live item passed unless it was executed. The checked-in production-helper benchmark does not exercise Podman, Chromium, upstream search engines, model inference, llama.cpp, or WebUI.

The latest workstation-specific live results and explicit nonclaims are recorded
in [`docs/benchmarks/publication-live-validation-2026-08-02.md`](docs/benchmarks/publication-live-validation-2026-08-02.md).
