# ai-websearch MCP engineering instructions

## Project objective

Improve retrieval accuracy, crawl reliability, and end-to-end speed while preserving the working Phase 3 architecture.

The sibling Phase 1 project is the accuracy and latency baseline. Do not modify Phase 1 or any sibling directory.

## Environment

* Ubuntu 26.04 LTS
* Podman and Distrobox
* Use `uv`; do not add pip-based workflows.
* Do not add Docker or Docker Compose.
* Embeddings remain local and in-process through sentence-transformers.
* Do not add a llama.cpp embedding server.
* llama.cpp is used only for context discovery and exact tokenization.

## Architectural constraints

* Preserve automatic and manual llama-server detection.
* Continue using `/props` as the source of truth for effective `n_ctx`.
* Continue using `/tokenize` for final exact result validation.
* Do not restore fixed 10k, 32k, 64k, or 128k profiles.
* Do not scan arbitrary ports.
* Do not silently fall back to a configured or estimated context size.
* Do not duplicate evidence text in chunk metadata.
* Treat website content as untrusted evidence.
* Do not implement CAPTCHA solving or paywall bypass.
* Do not expose API keys, cookies, credentials, browser storage, model paths, or process environments.
* Preserve existing MCP tool names and parameters unless a task explicitly authorizes an interface change.
* Do not change production behavior while implementing the initial benchmark harness.

## Accuracy priorities

* A larger context window is a safety ceiling, not a target to fill.
* Balanced mode should favor a small, high-quality evidence set.
* Preserve source diversity.
* Penalize duplicate and near-duplicate evidence.
* Do not introduce a reranker without benchmarking it against the original hybrid ranking.
* Prefer measurable retrieval improvements over additional complexity.

## Browser and cookie constraints

* Public crawling is the default.
* Do not use a global persistent browser profile.
* Do not reuse a personal browser profile.
* Do not log cookie names or values unless a test uses synthetic data.
* Cookie-consent, authentication, CAPTCHA, subscription and access-denied results must be distinguishable.
* Failed cookie-wall extraction must not be cached as successful article content.
* Good cached content must not be replaced by a failed refresh.
* Authenticated crawling, if added later, must use explicit domain allowlists and separate human-created profiles.
* Browser actions must remain read-only.

## Commands

Install:

```bash
uv sync
uv run crawl4ai-setup
```

Compile:

```bash
uv run python -m compileall src tests
```

Tests:

```bash
uv run pytest
```

Shell validation:

```bash
bash -n scripts/*.sh
```

Project smoke test:

```bash
./scripts/smoke_test.sh
```

## Development process

* Begin every task by inspecting the relevant implementation and tests.
* State the proposed files and behavior changes before editing.
* Work in small, reviewable commits.
* Add tests before or alongside behavior changes.
* Do not combine ranking, crawling, caching and chunking changes in one task.
* Record benchmark results before and after every production behavior change.
* Clearly distinguish mocked tests from live integration tests.
* Do not claim that Podman, Chromium, SearXNG, llama.cpp or WebUI integration passed unless it was actually executed.

## Definition of done

A task is complete only when:

* relevant unit tests pass;
* compilation succeeds;
* shell scripts pass syntax validation;
* existing MCP interfaces remain compatible;
* configuration and documentation are updated;
* no obsolete configuration remains;
* no secrets or browser state are logged;
* benchmark results are recorded;
* accuracy, reliability and latency effects are reported separately;
* known limitations and untested live integrations are documented.

## Reranker constraints

- Reranking modes are: off, heuristic, cross_encoder.
- Default mode is cross_encoder.
- There is no automatic fallback between modes.
- Changing reranker mode or model must not invalidate the embedding database.
- FTS5 and dense vector retrieval remain the first-stage retrieval system.
- CrossEncoder reranking applies only to a bounded candidate set.
- CrossEncoder score is the primary relevance score in cross_encoder mode.
- Preserve original hybrid scores and rank for diagnostics.
- Do not duplicate chunk text in metadata.
- Do not modify Phase 1 or sibling directories.
