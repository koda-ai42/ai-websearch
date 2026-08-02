# Publication live validation — 2026-08-02

Environment: Ubuntu 26.04 host, rootless Podman 5.7.0, Python 3.12,
Crawl4AI 0.9.1, Sentence Transformers 5.6.0. Values below are observations from
one local workstation, not portable performance claims.

## Passed

- The checksum-verified Gitleaks 8.30.1 scanner reported zero findings across
  all rewritten Git history and the current directory (including archives to
  depth two). Reports were redacted and stored outside the repository.
- The release checker found no forbidden path in the current tree, any Git ref,
  the wheel, or the sdist. `git fsck --full --no-reflogs --unreachable` reported
  no leftover objects after the history rewrite.
- The official pinned SearXNG digest resolved to an OCI index with three
  platform manifests.
- An already-running loopback SearXNG responded to `/config` with 279 available
  and 83 enabled engines; one real upstream search probe succeeded.
- Automatic llama-server discovery found one verified loopback server. Manual
  configuration against the same endpoint also passed. Both modes verified
  `/props`, an effective context of 124,928 tokens, and `/tokenize`.
- Crawl4AI's browser doctor crawled its public test page successfully in 2.68 s.
  ai-websearch then crawled `https://example.com` through its own ephemeral
  browser path in 0.86 s, returning success, HTTP 200, 165 extracted characters,
  and a public canonical origin.
- The pinned embedding model returned two normalized 384-dimensional vectors.
  Its first observed call took 3,897.94 ms; its warm two-text call took 17.21 ms.
- The pinned 17M CrossEncoder ranked the relevant synthetic passage first. Its
  first observed two-candidate call took 1,228.35 ms; its warm call took 5.49 ms.
  Peak process RSS with both models loaded was 948,080 KiB.
- One live rapid research request traversed search, crawl, SQLite, embeddings,
  CrossEncoder, packing, `/props`, and exact `/tokenize`. It stopped on
  sufficient evidence after 11.54 s with two sources, four chunks, a 6,296
  character context, answerable-with-citations status, and zero warnings.
- A real FastMCP Streamable HTTP client connected to
  `http://127.0.0.1:8050/mcp`; the default process exposed exactly one tool,
  `research`. The temporary process was stopped after the check.

## Not executed or not claimed

- The new `ai-websearch-searxng` container was not created because an older
  loopback SearXNG instance already owns port 8888. The older container uses a
  mutable image tag and was used only for functional probing; it was not stopped
  or modified. The new status script correctly reported that its distinct
  managed container is absent.
- No SearXNG engine override, container update, or restart was performed.
- No real third-party CAPTCHA was solved or bypassed. CAPTCHA, authentication,
  consent, subscription, access denial, HTTP error, retry, stale-cache, robots,
  and canonical-redirect behavior remain covered by synthetic/offline tests;
  the complete synthetic browser matrix was not run live.
- GPU model inference was not run. Timings above are single CPU observations,
  not p50/p95 distributions.
- A llama-ui/Open WebUI client was not running, so frontend rendering and
  clickable citations were not exercised. The active llama-server did have its
  MCP proxy and tool-template support enabled, but that is not a frontend pass.
- GitHub-hosted Actions, CodeQL, Dependabot, secret scanning/push protection,
  private vulnerability reporting, protected-branch rules, and PyPI upload were
  not exercised because no GitHub remote or owner is configured.
