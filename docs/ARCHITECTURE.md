# Architecture

## Request path

1. The rapid/deep/auto controller resolves request-wide page, source, and chunk ceilings, then chooses a bounded pass.
2. Query planning keeps the original query and adds only small intent-derived variants; it does not append source-authority instructions.
3. SearXNG result lists are merged with per-query reciprocal-rank fusion, canonical URL deduplication, and a small per-domain cap. Partial query failures remain observable; total SearXNG failure is not reported as an ordinary empty result.
4. Public URLs pass syntax, credential, denylist, DNS, and private-network checks before an ephemeral Chromium crawl. Crawl4AI robots checking is enabled by default.
5. HTTP status, robots denial, access walls, empty content and extraction failure are classified distinctly and rejected. Relative canonical links are resolved against the final page URL and must pass public-network policy before storage or citation. High-confidence consent chrome and trailing site-navigation sections are removed before a post-extraction quality gate rejects consent-only pages and generic navigation shells. Successful public content is section-aware chunked, embedded locally, and stored without repeated security boilerplate. Heading/list boundaries remain intact and overlap never begins in the middle of a word or structured section.
6. SQLite FTS5 and dense dot-product retrieval produce the first-stage pool. Weighted reciprocal-rank fusion avoids assuming that BM25 and cosine score magnitudes are comparable. Conditional freshness contributes 10% only for temporal queries. Publication dates carry `json_ld`, `meta`, `time`, or `search_result` provenance, and implausibly future dates are ignored.
7. Exact and near duplicates are removed. A bounded relevance filter applies the same content-quality policy to every candidate, then removes very short or uncovered candidates before the configured reranker. It never force-fills the reranker pool with rejected content.
8. CrossEncoder mode makes its query-passage score primary. `off` and `heuristic` are explicit alternatives with no fallback. Original first-stage rank/scores remain diagnostic fields.
9. Novelty and per-source caps select a compact evidence set. The controller assesses this packable set—not an earlier candidate prefix—before stopping. Sources carry real URLs and Markdown hyperlink citations; untrusted-evidence boundaries are added only while rendering model context.
10. llama.cpp `/props` determines the context ceiling and `/tokenize` validates the complete serialized result exactly.

The orchestration boundary uses a typed `ResearchRequest`, mutable
request-owned `ResearchRunState`, immutable per-pass results, and a separate
evidence-refresh function. This keeps search/crawl, retrieval, and final packing
independently testable while preserving one request-wide URL set, warning list,
deadline, and page-attempt ceiling.

## Agent stopping model

`rapid` executes one small pass with a two-page request ceiling. `deep` executes
one larger pass with a ten-page ceiling. `auto` has a five-page ceiling: it
always starts with a rapid pass of at most two pages and may spend the remaining
allowance in one deep pass only when evidence is absent, fails content quality,
has low query coverage, or lacks required diversity. Dense/keyword agreement
can support low-coverage evidence only when at least two sources remain. Query complexity remains an evidence-quality
signal; it no longer bypasses the rapid-first progression contract.
There is no separate categorical depth control. Numeric caller limits can only
tighten the mode defaults and the context/reranker safety ceilings apply last.

The result records `stop_reason`, mode defaults, requested limits, effective
limits, per-pass page use, and `answerability`. Sufficient evidence is a terminal condition, so
larger passes crawl in bounded stages and check evidence between stages. The MCP
system prompt tells the calling LLM to call `research` exactly once, abstain on
insufficient evidence, and include a provided citation plus fetched date when
answering. A machine-readable client contract makes `research` the only allowed
answer-generation tool. The contract requires the original question unchanged,
forbids unrequested scope expansion, and provides a transaction validator for
one-call/query/citation/fetched-date compliance. The default server publishes
only that tool; compatible
diagnostic and administrative tools are registered only in explicitly elevated
processes.
This prevents bounded research from turning into open-ended tool loops.

## Storage and cache

The schema retains document versions, marks exactly one version active per canonical URL, and uses a many-to-many source/topic association. Each source also records a versioned quality status. Fresh cache hits are revalidated when their quality policy is unknown or stale; unusable rows are quarantined and treated as cache misses. Quarantined chunks are excluded from FTS and dense retrieval without deleting source history. Stale unchanged or historically reappearing content reuses existing chunks/vectors. New unusable content is refused before a source write, and failed refreshes cannot replace good content.

`ai-websearch cache audit` is dry-run by default. `--apply` records current
quality decisions and quarantines unusable historical rows. Audit output
contains source IDs and classification reasons, never page text, cookie data,
credentials, or browser state.

Changing reranker mode/model does not touch embedding compatibility metadata. Changing the embedding model/dimension or the stored chunk representation remains a hard error until the database is rebuilt. Section-aware chunking uses embedding input version `clean_sections_v3`.

## Trust boundaries

- Search snippets and page content are untrusted evidence, never tool instructions.
- Public crawling rejects credential-bearing URLs and non-public DNS destinations. A browser request hook also blocks non-public subresources/redirects.
- Browser contexts are dedicated and ephemeral, downloads are disabled, and no personal profile is reused.
- CAPTCHA is a terminal noncacheable outcome; the software does not solve challenges or open an interactive browser.
- MCP and SearXNG bind to loopback by default.

## Known scaling boundary

Dense retrieval currently scans active vectors in-process. This keeps the local design dependency-light and is appropriate for a modest personal corpus, but it is linear in stored chunks. Add an ANN index only after corpus-size benchmarks show the scan is material; do not add infrastructure preemptively.
