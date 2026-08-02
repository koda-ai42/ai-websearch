# ai-websearch Optimization Plan (historical)

> This document records a historical pre-publication audit and benchmark design. References to current source scoring, raw cross-query merging, binary crawl outcomes, or append-only active versions describe the former implementation. See `ARCHITECTURE.md` and `PIPELINE_REVIEW.md` for current production behavior.

## Status and scope

This plan is approved for staged implementation. It compares the separate sibling Phase 1 baseline with the current Phase 3-derived implementation; the sibling project is read-only.

The first stage is strictly an evaluation and instrumentation harness. It must not change production retrieval behavior. Phase 1 remains an immutable baseline.

The comparison was based on static inspection. No live SearXNG, Chromium/Crawl4AI, sentence-transformer, llama.cpp, Podman, or WebUI integration was executed, and no databases were opened or inspected. Consequently, all accuracy and latency effects below are hypotheses to validate, not benchmark results.

## Executive conclusion

Phase 1 can produce more accurate answers because its default pipeline is narrower:

- With neutral scoring, Phase 1 normally issues only the user's original query. Current balanced mode issues three queries, including generic suffixes such as `official source` and `technical documentation`.
- Current code pools SearXNG scores from different query requests even though those scores are not calibrated across result sets.
- Phase 1 retrieves and packs at most eight chunks. Current balanced mode can pack 25 chunks from up to nine sources without a minimum relevance threshold.
- Current packing treats the context budget as capacity that may be filled instead of independently deciding whether more evidence is useful.
- Phase 1's 12,000-character ceiling can act as a useful noise regularizer.

The current implementation is materially better at exact context safety, source diversity, candidate recall, and metadata reporting. Those improvements do not guarantee answer accuracy because evidence precision is not measured or used to stop packing.

## Findings

### 1. Search-query generation

**Files and symbols:** Phase 1 `src/ai_websearch/orchestrator.py::plan_queries`; current `src/ai_websearch/orchestrator.py::plan_queries`.

**Phase 1 behavior:** Under the default neutral scoring mode, emits only the original query. It adds `official source` only for quality/custom scoring and `latest` only for day/month freshness.

**Current behavior:** Balanced mode emits three of eight hard-coded variants: normally the original query, `official source`, and `technical documentation`. Year freshness can also add `latest`.

**Expected accuracy effect:** Likely negative for current on nontechnical, comparative, experiential, and ambiguous questions because the suffixes can cause query drift. Potentially positive for documentation questions.

**Expected reliability effect:** More search calls create more opportunities for partial failure, although failures are isolated.

**Expected speed effect:** Approximately three times the default search-request work because calls are sequential.

**Confidence:** High.

**Test needed:** Use fixed SearXNG fixtures and measure URL precision/recall and downstream evidence relevance for factual, technical, news, consumer, and ambiguous query classes.

### 2. Multi-query result pooling

**Files and symbols:** Phase 1 and current `src/ai_websearch/orchestrator.py::search_many`.

**Phase 1 behavior:** Usually pools one result list under neutral defaults, so SearXNG scores come from one request.

**Current behavior:** Pools up to three balanced or eight exhaustive result lists, then globally sorts raw `(source_score, score)` values. Raw SearXNG scores from different query requests are assumed comparable.

**Expected accuracy effect:** Likely negative for current. A high score from a weak variant can displace an original-query result. This is one of the strongest explanations for a Phase 1 advantage.

**Expected reliability effect:** Individual query failures still permit partial results.

**Expected speed effect:** Latency grows approximately linearly with query count because searches are serial.

**Confidence:** High for the mechanism; medium-high for its practical impact.

**Test needed:** Replay per-query fixtures with deliberately different score scales and compare pooled precision against per-query normalization and rank fusion.

### 3. SearXNG ranking and deduplication

**Files and symbols:** `src/ai_websearch/search.py::web_search`; `src/ai_websearch/orchestrator.py::search_many`.

**Phase 1 behavior:** Performs exact normalized-URL deduplication and lexicographically sorts by source score first and SearXNG score second. Cross-query deduplication is exact URL equality.

**Current behavior:** Uses the same algorithm, but additional queries make its limitations more consequential. Canonical-equivalent URLs, query variants not covered by the tracking-parameter list, AMP/mobile variants, and mirrors remain distinct. A repeated URL's last result replaces its earlier metadata.

**Expected accuracy effect:** Current is more exposed to duplicate crowding and incomparable scores.

**Expected reliability effect:** Neutral.

**Expected speed effect:** More redundant crawls and embeddings in current.

**Confidence:** High.

**Test needed:** Cover tracking and nontracking parameters, redirects, canonical variants, AMP/mobile URLs, and duplicate URLs with differing titles and scores. Measure unique canonical sources in the scrape set.

### 4. Source scoring

**Files and symbols:** Phase 1 and current `src/ai_websearch/source_scoring.py::quality_score_source`; current `custom_score_source`.

**Phase 1 behavior:** Neutral default is 0.5. Optional quality mode uses domain, path, and keyword heuristics.

**Current behavior:** Retains the same default and quality heuristics and adds YAML domain lists for custom mode. The shipped lists are empty.

**Expected accuracy effect:** No default difference. In quality/custom mode, authority can dominate topical relevance because source score is the primary sort key. The word `official` in a snippet is an unreliable signal.

**Expected reliability effect:** Custom mode depends on a working-directory-relative configuration path.

**Expected speed effect:** Negligible except for repeatedly parsing YAML in custom mode.

**Confidence:** High.

**Test needed:** Label source authority and topical relevance separately; evaluate ordering under neutral, quality, and populated custom policies. Test startup from a non-project working directory.

### 5. Search-time score reuse after crawling

**Files and symbols:** `src/ai_websearch/search.py::web_search`; `src/ai_websearch/orchestrator.py::ingest_url`.

**Phase 1 behavior:** Passes the score computed from the SearXNG title/snippet as a hint, so the extracted page is not rescored.

**Current behavior:** Identical.

**Expected accuracy effect:** Negative in both. Misleading snippets, redirects, consent pages, and changed content retain the pre-crawl score. Current has more variant-result snippets and therefore more exposure.

**Expected reliability effect:** Extraction mismatch is not distinguished from other failures.

**Expected speed effect:** Slightly faster than rescoring, although scoring is cheap.

**Confidence:** High.

**Test needed:** Use fixtures where snippets and extracted content disagree, including redirects and consent walls, and compare search-time with post-extraction classification.

### 6. Browser lifecycle and Crawl4AI configuration

**Files and symbols:** `src/ai_websearch/scrape.py::scrape_url`.

**Phase 1 behavior:** Creates a new `AsyncWebCrawler` and browser context for every URL. Pages are scraped sequentially with a headless browser, custom user agent, overlay removal, excluded tags, and a 35-second timeout.

**Current behavior:** Identical, using the same locked Crawl4AI 0.9.1 dependency. Balanced mode scrapes five pages instead of Phase 1's default four.

**Expected accuracy effect:** No per-page difference; the extra current page may add recall or noise.

**Expected reliability effect:** Fresh contexts prevent cross-site contamination but lose useful same-session state.

**Expected speed effect:** Current is slower, and both repeatedly pay browser startup and teardown costs.

**Confidence:** High.

**Test needed:** Instrument browser startup, navigation, rendering, extraction, and teardown separately over cold and warm repeated runs.

### 7. Cookie and consent handling

**Files and symbols:** `src/ai_websearch/scrape.py::scrape_url` browser and run configuration.

**Phase 1 behavior:** Has no cookie seeding, consent classification, banner interaction, authentication classification, or dedicated profile. Overlay removal may remove only the visual overlay.

**Current behavior:** Identical.

**Expected accuracy effect:** Negative in both because consent-wall content can be accepted as article Markdown. The additional current sources increase exposure.

**Expected reliability effect:** Cookie consent, authentication, CAPTCHA, subscription, and access-denied outcomes are not distinguishable.

**Expected speed effect:** A blocked result can consume a full crawl without a useful result.

**Confidence:** High.

**Test needed:** Synthetic pages for consent, authentication, CAPTCHA, subscription, access denied, and an overlay covering otherwise public content. Confirm that wall text is never stored as article content.

### 8. Page extraction and Markdown selection

**Files and symbols:** `src/ai_websearch/scrape.py::_markdown_from_result`; `src/ai_websearch/clean.py::clean_markdown`.

**Phase 1 behavior:** If `result.markdown` is a string, always selects it. For an object, tries `fit_markdown`, then `raw_markdown`, then citation Markdown. It makes no content-quality comparison and truncates output to 60,000 characters before chunking.

**Current behavior:** Identical.

**Expected accuracy effect:** Neutral between phases but potentially poor in both. Boilerplate may be selected, fit Markdown quality is not evaluated, and character truncation can discard a relevant tail.

**Expected reliability effect:** Empty content is detected; low-quality and wall content are not.

**Expected speed effect:** Simple and fast.

**Confidence:** High.

**Test needed:** Crawl a labeled set of articles, documentation, forums, SPAs, and navigation-heavy pages. Score each Markdown variant for main-content precision and answer-bearing recall.

### 9. Chunking

**Files and symbols:** `src/ai_websearch/chunking.py::chunk_text`.

**Phase 1 behavior:** Uses 1,200-character chunks with 180-character suffix overlap. Oversized blocks split on sentence punctuation. Overlap can start mid-word or mid-structure, and chunks shorter than 180 characters can be discarded.

**Current behavior:** Identical.

**Expected accuracy effect:** Neutral between phases. Both can lose short decisive facts, split tables/code/headings from their content, and generate overlapping near-duplicates.

**Expected reliability effect:** Deterministic.

**Expected speed effect:** Fast.

**Confidence:** High.

**Test needed:** Boundary-recall tests for short answers, tables, lists, code, headings, long sentences, and Unicode. Measure whether answer spans remain intact.

### 10. Embedding generation

**Files and symbols:** `src/ai_websearch/embeddings.py::Embedder`; render-time evidence boundaries in `src/ai_websearch/context_packer.py`.

**Phase 1 behavior:** Uses the local `all-MiniLM-L6-v2` model, lazy singleton loading, normalized embeddings, and batch size 32. Stored chunks include a repeated untrusted-content prefix while queries do not.

**Current behavior:** Identical.

**Expected accuracy effect:** Neutral between phases. Repeated boilerplate creates document/query asymmetry and consumes model input capacity. Long chunks can approach or exceed the model's effective token limit, making tail content invisible to the embedding.

**Expected reliability effect:** Model and dimension checks are good; a model failure aborts ingestion.

**Expected speed effect:** Warm batching is efficient, but unchanged recrawls are embedded before duplicate detection.

**Confidence:** High for the asymmetry; medium-high for its measured impact.

**Test needed:** Compare retrieval with embeddings of raw versus wrapped content. Add long-chunk tail-answer tests and record model truncation.

### 11. FTS5 retrieval

**Files and symbols:** `src/ai_websearch/store.py::keyword_search`.

**Phase 1 behavior:** Passes nearly the entire natural-language question directly to FTS5 `MATCH`. FTS syntax errors silently become an empty keyword result. BM25 is transformed with `1 / (1 + abs(rank))`.

**Current behavior:** Identical, with a larger candidate request.

**Expected accuracy effect:** Potentially more recall in current, but both risk overly restrictive term matching and silent loss of the keyword channel. The BM25 transform compresses scores before normalization.

**Expected reliability effect:** Low observability because all `sqlite3.OperationalError` exceptions are swallowed.

**Expected speed effect:** FTS is fast; larger result limits modestly increase work.

**Confidence:** High.

**Test needed:** Cover stopwords, punctuation, operators, quotation marks, long questions, rare terms, and malformed syntax. Compare with explicit query parsing and record keyword-channel failure rate.

### 12. Vector retrieval

**Files and symbols:** `src/ai_websearch/retrieval.py::retrieve`; `src/ai_websearch/store.py::fetch_all_chunks`.

**Phase 1 behavior:** Loads every matching chunk and computes NumPy dot products in Python. Research takes the best eight from up to 50 candidates.

**Current behavior:** Uses the same implementation, but balanced research asks for up to 150 returned candidates before packing.

**Expected accuracy effect:** Current has higher candidate recall but exposes more weak candidates to the packer.

**Expected reliability effect:** Memory use and latency degrade with corpus size.

**Expected speed effect:** Current sorting and materialization are heavier; both scan all topic chunks.

**Confidence:** High.

**Test needed:** Measure recall at 8, 25, 50, and 150 against labeled relevant chunks, plus latency and peak RSS over increasing corpus sizes.

### 13. Score normalization and fusion

**Files and symbols:** `src/ai_websearch/retrieval.py::_minmax`; `retrieve`.

**Phase 1 behavior:** Performs per-query min-max normalization, combines 0.70 vector and 0.30 keyword scores, then applies a 0.85-1.0 source multiplier. Equal-score sets all become 1.0.

**Current behavior:** Identical, but larger candidate sets change normalization endpoints.

**Expected accuracy effect:** A single outlier can compress other scores; absent channels receive zero; singleton and equal-score sets appear maximally relevant. There is no calibrated threshold. Current candidate size makes ranks more corpus-sensitive.

**Expected reliability effect:** Deterministic but corpus-sensitive.

**Expected speed effect:** Negligible.

**Confidence:** High.

**Test needed:** Use controlled score sets containing outliers, equal scores, missing keyword hits, and growing candidate pools. Measure rank stability and nDCG.

### 14. Source and chunk diversity

**Files and symbols:** Phase 1 `src/ai_websearch/context_packer.py::pack_context`; current `src/ai_websearch/context_packer.py::_select`.

**Phase 1 behavior:** Selects up to eight chunks, at most two per source, with no total source cap. The duplicate fingerprint covers the first 600 normalized characters.

**Current behavior:** Balanced mode can select 25 chunks, at most three per source, from at most nine sources. The fingerprint covers 700 characters.

**Expected accuracy effect:** Current diversity can improve coverage and reduce source domination, but the much larger allowance can dilute strong evidence. Nine sources and 25 chunks are inconsistent with a small balanced evidence set.

**Expected reliability effect:** Deterministic.

**Expected speed effect:** More packing and tokenization.

**Confidence:** High for behavior; medium-high for accuracy impact.

**Test needed:** Compare answer accuracy and evidence precision at 6, 8, 12, and 25 chunks with per-source caps of 1, 2, and 3.

### 15. Near-duplicate detection

**Files and symbols:** Same context-packer symbols as source/chunk diversity.

**Phase 1 behavior:** Removes only exact equality of a lowercased, whitespace-normalized 600-character prefix.

**Current behavior:** Uses the same approach with 700 characters.

**Expected accuracy effect:** Effectively neutral between versions. Both miss syndicated, templated, lightly edited, shifted-prefix, and overlapping evidence. The current larger context increases duplicate risk.

**Expected reliability effect:** Deterministic.

**Expected speed effect:** Very fast.

**Confidence:** High.

**Test needed:** Use synthetic and real syndicated-page pairs and report duplicate rate after selection. Token shingles or semantic similarity may be used as evaluation metrics without changing production behavior.

### 16. Context packing

**Files and symbols:** Phase 1 `src/ai_websearch/context_packer.py::pack_context`; current `src/ai_websearch/context_packer.py::_render_context` and `pack_context`.

**Phase 1 behavior:** Uses a 12,000-character hard cap and normally eight chunks. It stops when full and may truncate the final chunk.

**Current behavior:** Uses a dynamic llama context budget and permits up to 25 balanced chunks. It selects by rank until the count limit, with no relevance floor, novelty-gain test, or enough-evidence stopping rule.

**Expected accuracy effect:** This is likely the largest Phase 1 advantage. Phase 1's smaller cap can improve evidence precision and reduce answer distraction. Current improves recall and conflict coverage but can overpack weak evidence.

**Expected reliability effect:** Current safely enforces model context limits.

**Expected speed effect:** Current is substantially slower.

**Confidence:** High for the mechanism; medium-high for the outcome.

**Test needed:** Blind answer evaluation across context sizes, measuring evidence precision, citation correctness, contradiction handling, and unsupported-answer behavior.

### 17. Exact tokenization

**Files and symbols:** Current `src/ai_websearch/context_packer.py::_stable_count`; `src/ai_websearch/llama_client.py::count_tokens`.

**Phase 1 behavior:** Uses a character ceiling and performs no exact model tokenization.

**Current behavior:** Uses llama.cpp `/tokenize` on the complete serialized MCP response. A normal fit repeatedly tokenizes empty and full payloads; trimming repeats the process, and final-chunk binary search can require many more requests.

**Expected accuracy effect:** Positive for current because it prevents overflow and downstream truncation. It does not address whether the selected evidence is too noisy.

**Expected reliability effect:** Exact and fail-closed, but research now depends on a live tokenizer.

**Expected speed effect:** Strongly negative.

**Confidence:** High.

**Test needed:** Count `/tokenize` calls and wall time for no-trim, multi-chunk trim, and binary-search cases. Verify exact counts for the serialized response.

### 18. Error handling

**Files and symbols:** `src/ai_websearch/search.py::web_search`; `src/ai_websearch/scrape.py::scrape_url`; `src/ai_websearch/orchestrator.py::search_many`; current `src/ai_websearch/server.py::main`.

**Phase 1 behavior:** Search retries three times; per-query and per-page failures permit partial results and warnings. FTS errors disappear. Research does not require llama.cpp.

**Current behavior:** Retains search/crawl behavior, but startup, research, and retrieval require verified `/props` and `/tokenize`. Token failures abort instead of returning an unsafe estimate.

**Expected accuracy effect:** Fail-closed behavior prevents invalid context but produces no answer where Phase 1 could still answer.

**Expected reliability effect:** Current is safer but less available because llama-server is a hard dependency.

**Expected speed effect:** Discovery, `/props`, and `/tokenize` add latency.

**Confidence:** High.

**Test needed:** Fault injection for partial search failure, scrape timeout, malformed FTS queries, llama authentication, stale detection cache, invalid `/props`, and `/tokenize` outage.

### 19. Cache behavior

**Files and symbols:** `src/ai_websearch/scrape.py::scrape_url`; `src/ai_websearch/store.py::store_document`.

**Phase 1 behavior:** Always bypasses the Crawl4AI cache. Duplicate canonical URL plus content hash is detected only after scraping, chunking, and embedding. Changed content creates another source record and old versions remain.

**Current behavior:** Identical. `cache_ttl_hours` exists but is unused. Llama discovery alone has a 300-second cache.

**Expected accuracy effect:** Both can retrieve stale and current versions simultaneously, producing duplication or contradictions. Neither protects good cached content from a failed refresh.

**Expected reliability effect:** Every refresh depends on the network; failed refreshes cannot use known-good content.

**Expected speed effect:** Repeated crawling and embedding are wasteful.

**Confidence:** High.

**Test needed:** Repeated unchanged URL, changed page, failed refresh after a good fetch, canonical change, and multiple-topic ingestion tests using disposable databases.

### 20. Stage-level latency and observability

**Files and symbols:** Pipeline symbols above and `src/ai_websearch/logging_utils.py`.

**Phase 1 behavior:** Has no stage timers or benchmark harness. The default path is approximately one serial search, four serial browser lifecycles, four embedding batches, one full vector scan, and local character packing.

**Current behavior:** Also lacks stage timers. Balanced mode is approximately three serial searches, five serial browser lifecycles, five embedding batches, one full vector scan with more candidates, llama detection/verification when cold, and multiple `/tokenize` calls.

**Expected accuracy effect:** Unmeasured latency can cause operational timeouts that appear to be accuracy failures.

**Expected reliability effect:** Regressions cannot be localized.

**Expected speed effect:** Current is statically expected to be slower end to end. No numeric claim is justified without measurement.

**Confidence:** High for missing instrumentation and operation counts; numerical impact unknown.

**Test needed:** Add monotonic stage timing and benchmark cold/warm p50 and p95 latency, operation counts, and peak RSS.

## Primary Phase 1 accuracy hypothesis

The leading causal hypothesis is:

1. Current balanced research generates three queries instead of usually one.
2. Results are pooled using raw cross-query SearXNG scores.
3. Generic query variants can displace relevant original-query results before crawling.
4. Five pages are ingested instead of four.
5. Up to 150 chunks proceed toward selection instead of 50.
6. Up to 25 chunks from nine sources are packed instead of eight chunks under a 12,000-character ceiling.
7. No absolute relevance threshold, marginal-gain test, or early stopping rule is applied.
8. The answer model receives more evidence, but a lower proportion may directly answer the question.

This must be confirmed with the evaluation harness before changing production behavior.

## Staged implementation plan

### Stage 1: Evaluation and instrumentation harness only

This stage must not alter production retrieval behavior.

Add an offline benchmark command under `benchmarks/` or `scripts/` using existing dependencies and disposable temporary databases. The harness should contain:

- A versioned query set covering exact factual lookup, technical documentation, current events, comparative/consumer questions, multi-hop questions, ambiguous questions, no-answer cases, conflicting-source cases, and crawl-access classifications.
- Captured, replayable SearXNG and Crawl4AI fixtures so Phase 1 and current behavior can be evaluated on identical inputs.
- Read-only trace hooks or wrapper-level monotonic timing around query planning, every search, merging/deduplication, each crawl and extraction, cleaning, chunking, embedding load and encode, database writes, FTS, vector scan, normalization/fusion, diversity selection, rendering, every `/props` and `/tokenize` request, and total wall time.
- Explicit separation between mocked/offline tests and live integration tests.

Record these accuracy metrics:

- Search precision and recall.
- Unique canonical-source and domain counts.
- Relevant-page recall.
- Answer-bearing chunk recall at k.
- Chunk precision at k.
- Duplicate rate.
- Source diversity.
- MRR and nDCG.
- Packed-evidence precision.
- Citation support and final-answer correctness under a fixed evaluation protocol.

Record these reliability metrics:

- Classified crawl outcomes.
- Partial-result rate.
- Per-stage failure rate.
- Preservation of good content after a failed refresh.
- llama detection and tokenization failure rates.

Record latency separately as cold/warm p50, p95, operation counts, and peak RSS.

**Stage acceptance criteria:**

- Production retrieval output is byte-for-byte or structurally unchanged with instrumentation disabled.
- No production interface changes.
- All benchmark databases and artifacts use temporary or explicitly isolated paths.
- Phase 1 and current baseline results are recorded before any production behavior change.
- Accuracy, reliability, and latency results are reported separately.

### Stage 2: Search planning and result merging

Benchmark independently:

- Original-query-only behavior.
- Existing suffix expansion.
- Query-type-aware expansion.
- Per-query rank fusion instead of raw cross-query score comparison.
- Canonical-aware deduplication and per-domain limits.

Do not change crawling, post-ingestion ranking, chunking, or context packing in this stage.

### Stage 3: Crawl reliability and extraction classification

Add explicit outcomes for success, cookie consent, authentication, CAPTCHA, subscription, access denied, empty content, and extraction failure. Evaluate available Markdown variants and reject wall content.

Benchmark a scoped ephemeral browser lifecycle where it may help. Preserve public, read-only crawling; do not use personal or global persistent profiles, solve CAPTCHAs, or bypass paywalls.

### Stage 4: Cache correctness

Introduce a URL/canonical cache policy with TTL and provenance:

- Consult known-good content before refresh.
- Do not cache failed walls as successful content.
- Do not replace good content after a failed refresh.
- Detect unchanged content before chunking and embedding.
- Define version replacement or active-version semantics so stale and current copies do not compete unintentionally.

### Stage 5: Retrieval evaluation and controlled fixes

Change and benchmark these independently:

1. FTS query construction and error observability.
2. Vector candidate scaling.
3. Score calibration and fusion.
4. Source-score use.

Benchmark every alternative against the original 0.70/0.30 hybrid ranking. Do not introduce a reranker unless it beats that baseline on accuracy with latency reported separately.

### Stage 6: Source and chunk diversity

Evaluate canonical, source, and domain deduplication; near-duplicate penalties; per-source caps; and marginal novelty. Preserve source diversity, while measuring whether diversity displaces stronger corroborating evidence.

### Stage 7: Context packing policy

Make balanced mode select a small, high-quality set by evaluating:

- A relevance floor or confidence gate.
- Marginal evidence-gain stopping.
- Explicit conflict and corroboration handling.
- A conservative balanced cap derived from benchmark results.
- Exact token budget retained as a safety ceiling, not a target.

Compare against both Phase 1's eight-chunk/12,000-character behavior and the current 25-chunk behavior.

### Stage 8: Performance optimization

After accuracy decisions are fixed, evaluate:

- Safe HTTP-client reuse.
- Reduced redundant browser startups.
- Skipping embeddings for unchanged content.
- Removing redundant stable-token-count calls while preserving final exact `/tokenize` validation.
- Vector-scan optimization only where corpus-scale benchmarks justify it.

Record before-and-after benchmarks for every production behavior change and continue reporting accuracy, reliability, and latency separately.

## Definition of done for the optimization program

Each stage is complete only when relevant unit tests pass, compilation succeeds, shell scripts pass syntax validation, MCP interfaces remain compatible, documentation and configuration are current, obsolete configuration is removed, secrets and browser state are not logged, benchmarks are recorded, and accuracy/reliability/latency effects are separately reported.

Live Podman, Chromium, Crawl4AI, SearXNG, llama.cpp, and WebUI integrations must be clearly identified as executed or untested. No integration may be claimed as passing unless it was actually run.
