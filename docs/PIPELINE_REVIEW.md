# Pipeline review

## Current production pipeline

### Search quality

- Cross-query SearXNG scores are no longer treated as a common numeric scale. Per-query rank fusion, canonical deduplication, and a two-result domain cap prevent one engine/query/domain from dominating.
- Query expansion is deliberately small and intent-based. There are no website authority lists or “credible source” knobs.
- FTS5 now uses safely quoted OR terms, title weighting, and the correct ascending BM25 direction. Dense and keyword channels are fused by rank; the original min-max score/rank remains diagnostic.
- Freshness is conditional. Explicit `day`/`month`/`year` settings or temporal language activates a small date component; unknown dates are neutral rather than automatically bad.
- A shared deterministic content-quality policy rejects consent-dominant content and generic navigation shells after extraction, on cache reuse, and before bounded reranking. The filter no longer force-fills a minimum candidate pool with rejected passages. CrossEncoder score remains primary only among eligible candidates; raw scores are not evidence-sufficiency probabilities.
- Exact/near duplicates and per-source caps keep packed evidence small and diverse.
- The controller evaluates the final packable chunk selection. One low-coverage source cannot pass merely because dense and keyword retrieval both selected it.

### Reliability and efficiency

- Rapid/deep/auto modes have explicit request-wide page/source/chunk ceilings,
  finite pass counts, time budgets, evidence gates, and stop reasons. `auto`
  shares five page attempts across its initial pass and at most one escalation.
  Larger passes check evidence after bounded crawl stages and can stop below
  their page ceiling.
- Fresh cache hits skip crawl and embedding. Unchanged or reverted content reuses existing vectors. Changed content retains history but only one canonical version is active.
- Cache rows carry a versioned quality status. Unknown or stale rows are revalidated on reuse; unusable historical rows can be quarantined with a dry-run-first audit and are excluded from both retrieval channels without deletion.
- Search and crawl calls share concurrency/rate limits, retry finitely, and stop retrying classified access walls.
- Retrieval reuses the already loaded active chunk rows instead of fetching candidate rows from SQLite twice.
- Answer-agent instructions require exactly one aggregate `research` call, explicit abstention on insufficient evidence, and a provided citation plus fetched date. Low-level tools remain available only for diagnostic/admin clients, so the client must enforce the published allowlist.

### Security

- URLs with credentials/credential-like query fields, non-HTTP schemes, denylisted domains, local names, private IP literals, or non-public DNS results are rejected. Browser routing repeats public-network checks for destination hosts.
- Chromium is dedicated and ephemeral; persistent/personal profiles, downloads, stored browser state, and automated challenge solving are disabled.
- Access-wall text is never cached as successful evidence, failed refreshes do not replace good content, and SQLite files are mode `0600`.
- Generic failures do not return internal paths or credential-bearing exception strings. Local model paths are reduced to a safe label.
- Search/page text remains explicitly untrusted and is separated from answer instructions.

## Recommended next improvements, in order

1. Expand the judged evaluation set. The new production-helper benchmark proves the FTS direction bug and controlled fusion behavior, but it is small. Add 30–50 representative local-LLM questions with relevance judgments before changing weights, query planning, chunk size, or reranker model.
2. Measure dense-scan scaling. Current dense retrieval is linear in active chunks. Record p50/p95 latency at 1k, 10k, and 100k chunks; add an embedded ANN index only when that scan is materially slow.
3. Improve publication-date extraction with JSON-LD and validate dates against fetch time. This should precede increasing freshness influence because many sources still lack dates.
4. Reuse one crawler process within a research pass while keeping a new isolated context per page. Browser startup is likely the dominant crawl cost, but this needs live memory/leak and isolation tests first.
5. Add HTTP conditional refresh (`ETag`/`Last-Modified`) before a stale browser crawl. Keep the current content-hash guard as the final correctness check.
6. Add engine-health diagnostics from SearXNG response metadata so repeatedly failing engines can be disabled by the user. Do not silently change the engine set.
7. Add section-aware chunking only if judged retrieval shows that character windows split answer-bearing passages. Avoid LLM-generated chunk summaries or duplicated evidence metadata.

## Residual security concerns

- DNS checks and browser DNS resolution are separate operations, so DNS rebinding cannot be eliminated completely at application level. Stronger deployments should isolate the browser in a network namespace with explicit egress rules.
- The default SearXNG image is pinned by digest. Review and deliberately update
  that digest rather than switching to a mutable tag.
- Prompt-injection pattern detection is advisory; no finite marker list can identify all adversarial prose. The primary controls remain evidence/instruction separation and a calling model that follows the supplied system prompt.
- MCP has no built-in user authentication. Loopback binding is a security boundary, not merely a default preference.
- Dependency/model downloads are supply-chain inputs. Keep `uv.lock`, review lock/model changes, and prefer pre-vetted local model artifacts for offline use.
- A public Git history may already contain `.env`, databases, logs, or generated artifacts even after `.gitignore` is added. Rotate any exposed secret and purge history before publication.

## Missing live/integration tests

- Rootless Podman lifecycle and SearXNG `/config`/search behavior on Ubuntu 26.04.
- Engine enable/disable/restart against the actual mounted configuration.
- Chromium installation and public static/JavaScript extraction.
- Redirect-time SSRF attempts and synthetic DNS-rebinding/network-namespace tests.
- Real access-wall classification with CAPTCHA remaining terminal and noninteractive.
- SearXNG/Crawl4AI throttling under multiple simultaneous MCP requests.
- llama.cpp auto/manual discovery, authenticated `/props`, `/tokenize`, and exact large-context packing.
- CrossEncoder startup/inference on CPU/CUDA, including memory pressure and concurrent requests.
- llama.cpp WebUI MCP rendering of Markdown hyperlinks and tool metadata.
- Enforcement of the answer-tool allowlist by each supported external client; the MCP server can publish instructions but cannot remove tools selectively for one caller.
- Long-running cache/version migration on a copy of a real database, plus interrupted-transaction recovery.

These are intentionally listed as unverified until run; mocked tests do not substitute for them.
