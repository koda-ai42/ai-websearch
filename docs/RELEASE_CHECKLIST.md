# Release checklist

## Identity and history

- [ ] Confirm the intended GitHub owner and that the owner-scoped repository
      name `ai-websearch` is available.
- [ ] Check PyPI immediately before upload. A prior 404 is not a reservation.
- [ ] Rotate every credential that may ever have appeared in `.env`, databases,
      logs, captured pages, or browser state.
- [ ] Keep a protected offline backup before rewriting history.
- [ ] Verify the public branch contains one root commit and no private
      development refs. Keep any pre-publication history only in the protected
      offline backup, never in a branch or tag pushed to GitHub.
- [ ] Run `scripts/check_release.py` against the current tree, every Git ref,
      and built archives.
- [ ] Run an independent secret scanner over all refs and objects.
- [ ] Verify the default branch is `main` and push sanitized history to a new
      private GitHub repository first.

## Reproducible offline gate

```bash
uv sync --frozen --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run python -m compileall src tests
uv run pytest -q -m 'not live'
bash -n scripts/*.sh
UV_CACHE_DIR=/tmp/ai-websearch-uv-cache ./scripts/smoke_test.sh
uv run python -m benchmarks --all
uv build --no-sources
uv run python scripts/check_release.py --artifacts dist
```

- [ ] Inspect wheel and sdist contents manually.
- [ ] Run `uv run python scripts/generate_sbom.py`; regenerate with `--write`
      only when the locked production dependency graph intentionally changed.
- [ ] Record accuracy, reliability, cold/warm p50/p95 latency, memory, and model
      load effects separately.

## Live release matrix

- [ ] Pull and run the pinned rootless Podman/SearXNG image; verify health,
      engine configuration, update procedure, and upstream searching.
- [ ] Run Chromium against public static/JavaScript pages plus synthetic
      CAPTCHA, consent, authentication, subscription, access-denied, HTTP-error,
      and robots-denied fixtures.
- [ ] Verify stale-if-error reuse and that failed refreshes do not replace good
      evidence.
- [ ] Run real embedding and CrossEncoder inference on supported CPU/GPU targets.
- [ ] Verify automatic and manual llama-server discovery, `/props`, and final
      `/tokenize` validation.
- [ ] Verify the MCP endpoint and citations from the intended llama-ui frontend.
- [ ] Document every live item that was not executed; do not infer a pass from
      mocked tests.

## GitHub controls and publication

- [ ] Push the complete tracked source tree with `git push`, rather than
      selecting files manually. This includes `src/`, tests, benchmarks,
      scripts, SearXNG configuration, documentation, `pyproject.toml`,
      `uv.lock`, the SBOM, and `.github/` automation/templates.
- [ ] Confirm `.env`, SQLite databases and sidecars, logs, browser state,
      captured pages, model weights/caches, container state/layers, and local
      build directories are neither tracked nor included in source archives.
- [ ] Attach only inspected wheel and sdist files from `dist/` to the GitHub
      release; do not commit `dist/` to the source branch.

- [ ] Enable protected-branch rules, required CI, secret scanning, push
      protection, CodeQL, Dependabot, and private vulnerability reporting.
- [ ] Confirm issue/PR templates, Code of Conduct, Security Policy, license,
      third-party notices, SBOM, changelog, and release notes render correctly.
- [ ] Confirm the SearXNG digest and all pinned GitHub Actions SHAs are reviewed.
- [ ] Make the repository public only after history and GitHub scans are clean.
- [ ] Tag the beta as `v0.1.0-beta.1`, build from that tag, inspect artifacts
      again, then publish. The Python distribution version is `0.1.0b1` so PyPI
      correctly recognizes it as a prerelease.
