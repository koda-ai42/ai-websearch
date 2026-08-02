# Benchmarking

> Stages 1–9 are frozen design-history replays. Some legacy fixtures and reports contain the removed `source_score` field so old results remain reproducible; current production code neither reads nor computes it. Stages 10–12 are current production-policy regression benchmarks.

## Stage 1 guarantees

The Stage 1 harness is outside `src/ai_websearch` and is never imported by production code. It does not alter MCP tools or search, crawl, extraction, chunking, embedding, storage, retrieval, ranking, fusion, diversity, packing, caching, context-budget, or tokenization behavior.

Offline replay is the default and requires no network, browser, llama.cpp server, model download, credential, cookie, browser profile, or existing database. The command temporarily sets `AI_WEBSEARCH_DATABASE_PATH` to a disposable directory before running and removes that directory afterward. The current offline implementation does not open even that disposable database; the isolation boundary is present for future benchmark adapters.

## Offline corpus

`benchmarks/fixtures/v1/corpus.json` is a versioned, deterministic captured-response-style corpus. It contains normalized SearXNG result records and Crawl4AI extraction outcomes. The cases cover:

- exact factual lookup;
- technical documentation;
- current events;
- comparative/consumer questions;
- multi-hop questions;
- ambiguous questions;
- no-answer questions;
- conflicting sources;
- success, consent, authentication, CAPTCHA, subscription, access-denied, empty-content, and extraction-failure crawl outcomes.

The harness replays the checked-in Phase 1 and current orchestration policies over the same records. It does not claim to execute either production implementation end to end. This separation prevents the benchmark from changing or depending on production behavior.

## Live judgment queue

`benchmarks/fixtures/live_v1/judgment_queue.json` defines 40 release-evaluation
questions spanning factual, documentation, current, comparative, multi-hop,
ambiguous, no-answer, conflict, access-policy and adversarial cases. It is
deliberately marked `human_review_required`: it must not be used for accuracy
claims until captured responses are frozen and a human records source relevance,
required claims, citation support and answerability. The repository does not
fabricate human judgments.

Run it with:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m benchmarks
```

Write an explicit artifact with:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m benchmarks \
  --output /tmp/ai-websearch-stage1.json
```

The checked-in baseline is `docs/benchmarks/stage1-offline-baseline.json`.

## Stage 2 search-policy comparison

Stage 2 remains benchmark-only. It compares search planning and merge policies without importing or changing production search code and without running crawling or downstream retrieval.

Run it with:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m benchmarks --stage 2
```

The separate `benchmarks/fixtures/stage2_v1/search_corpus.json` corpus covers incompatible cross-query score scales, technical documentation, current-event freshness, independent consumer analysis, canonical aliases, domain crowding, and multi-hop primary sources. Every policy receives the same captured-response-style records.

The compared policies are:

- `original_only`: only the user's original query with raw-score merging.
- `existing_suffix_expansion`: the current original/official/documentation expansion with raw-score merging.
- `query_type_aware_expansion`: category-specific offline planning for documentation, current events, consumer comparisons, multi-hop questions, and conflicts.
- `per_query_rrf`: existing expansion merged with reciprocal-rank fusion, avoiding direct comparison of raw scores from separate query requests.
- `canonical_dedup`: existing expansion with raw-score merging and canonical-URL identity.
- `canonical_dedup_domain_cap`: canonical deduplication plus a maximum of two results per domain.

The checked-in result is `docs/benchmarks/stage2-search-policy-results.json`. It reports accuracy, reliability, and deterministic latency/operation counts separately for each policy. Canonical aliases receive relevance credit only once, so duplicate URLs cannot inflate recall or nDCG.

These results are comparative fixtures, not a production-policy decision. The small synthetic corpus is designed to expose mechanisms rather than estimate general web-search quality. No policy should be promoted to production without a larger labeled corpus and the manual live matrix.

The canonical policies use canonical identities supplied by the offline fixture. A production implementation would first need a benchmarked, non-crawl-dependent way to obtain equivalent identity signals; Stage 2 does not add one.

## Stage 3 crawl and extraction comparison

Stage 3 remains benchmark-only. It evaluates crawl-outcome classification, Markdown selection precedence, wall rejection, and browser lifecycle models without importing or changing production crawl/extraction code.

Run it with:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m benchmarks --stage 3
```

The versioned `benchmarks/fixtures/stage3_v1/crawl_corpus.json` corpus covers successful extraction, cookie consent, authentication, CAPTCHA, subscription, access denied, empty content, and extraction failure. Successful cases exercise direct-string, fit, raw, and citation Markdown.

The extraction policies are:

- `current_behavior_model`: binary success/failure modeling with current direct/fit/raw/citation precedence.
- `explicit_current_precedence`: explicit access-outcome classification while retaining current Markdown precedence.
- `explicit_fit_first`: explicit classification with fit/raw/citation/direct precedence.
- `explicit_raw_first`: explicit classification with raw/fit/citation/direct precedence.
- `explicit_citations_first`: explicit classification with citation/fit/raw/direct precedence.

The lifecycle comparison models the existing fresh ephemeral browser per URL and a single scoped ephemeral browser for the benchmark batch. Both are declared read-only, use no persistent or personal profile, and have no cookies or credentials. The lifecycle timings are synthetic fixture durations, not observed browser performance.

The checked-in result is `docs/benchmarks/stage3-crawl-extraction-results.json`. It reports classification accuracy, Markdown-variant accuracy, wall-rejection rate, misclassification counts, lifecycle properties, and deterministic timing separately. Trace failure counts follow the fixture's actual crawl success/failure value; classifier disagreement is reported only through classification metrics.

The lifecycle model performs timing arithmetic only. It does not execute classification or verify that reuse preserves outcomes, so `expected_outcome_preservation` is reported as `null` for both lifecycle modes.

The explicit classifier deliberately uses simple fixture markers and achieves perfect accuracy on this small synthetic corpus. That result must not be interpreted as live classification accuracy. Real localization, JavaScript rendering, redirects, mixed article/wall pages, and provider-specific wording remain untested. No Stage 3 policy is connected to production.

## Stage 4 cache-correctness comparison

Stage 4 remains benchmark-only and uses an in-memory cache model. It does not import production storage code or open SQLite. Run it with:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m benchmarks --stage 4
```

The versioned `benchmarks/fixtures/stage4_v1/cache_corpus.json` corpus covers a fresh cache hit, unchanged stale refresh, changed content, failed refresh after good content, consent and authentication walls, canonical aliases, and a `v1 → v2 → v1` historical reversion.

The compared policies are:

- `current_append_model`: models no pre-refresh cache consultation, duplicate detection after chunk/embed work, and changed versions remaining simultaneously active.
- `replace_active`: consults a TTL cache, rejects non-success outcomes, skips unchanged preprocessing, and replaces the previous version.
- `retain_history_single_active`: applies the same safety behavior while retaining old versions as inactive history.

The checked-in result is `docs/benchmarks/stage4-cache-policy-results.json`. It reports cache correctness, good-content preservation, wall rejection, active-version correctness, avoided work, provenance completeness, deterministic operation counts, and synthetic latency separately.

Pre-refresh cache consultation is recorded as `database_read`, never `database_write`, and only for policies that perform it. Post-refresh content-identity checks are reported separately as `content_identity_read`. Database-write timing corresponds only to modeled cache writes.

When retained content reverts to an inactive historical version, that version is reactivated and every other version is made inactive. Replacement semantics must process and store the reverted content again because no historical copy remains.

Scenario-specific metrics are `null` when not applicable and aggregates include explicit applicable-case counts. This prevents unrelated scenarios from inflating cache-hit, wall-rejection, version, or unchanged-work scores.

The safe policies are idealized in-memory models, not production implementations. The small corpus does not evaluate concurrency, clock skew, transaction failures, storage growth, eviction, HTTP cache headers, redirects, cross-topic ownership, or process restarts. Stage 4 changes no production cache behavior.

## Stage 5 retrieval-policy comparison

Stage 5 is benchmark-only and uses pure in-memory fixture models. It does not import production retrieval/storage code or open SQLite. Run it with:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m benchmarks --stage 5
```

The versioned corpus covers natural-language and FTS-special queries, controlled vector candidate ranks at three corpus sizes, score-scale outliers, keyword-dominant evidence, and source-score tension. It compares raw silent FTS failure handling with observable and sanitized query models; vector candidate limits of 4, 8, 16, and 32; alternative calibration/fusion methods against the original min-max 0.70/0.30 hybrid; and source-score multipliers while holding fusion fixed.

Each family changes one modeled factor at a time. Fusion experiments retain the original source multiplier, and source-score experiments retain original fusion. No reranker is used. Accuracy, reliability/operation counts, and deterministic synthetic latency are reported separately in `docs/benchmarks/stage5-retrieval-policy-results.json`.

The FTS model is intentionally synthetic and does not claim exact SQLite parser compatibility. Vector timings do not measure embedding or SQLite performance, and all candidate policies model the same full-corpus comparison count. The small labeled corpus cannot establish a production winner; SQLite FTS behavior, controlled-size vector performance, and end-to-end answer quality remain manual live tests in a disposable environment.

FTS execution failures are reliability outcomes, not zero-quality retrieval results. Their per-case retrieval metrics are `null`; retrieval-quality aggregates exclude them and report `retrieval_quality_applicable_cases` explicitly.

## Stage 6 source and chunk diversity comparison

Stage 6 remains benchmark-only and uses a pure in-memory selection model. It does not import production retrieval code or open a database. Run it with:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m benchmarks --stage 6
```

The corpus covers canonical aliases, source and domain crowding, near-duplicate chunks, separately sourced corroboration, and novelty tradeoffs. It compares score order with canonical, source, and domain deduplication; a near-duplicate penalty; a two-chunk per-source cap; and marginal-novelty selection. Each alternative changes one modeled selection mechanism.

Accuracy gives each relevant evidence identity credit at most once, so aliases and near-duplicates cannot inflate precision, recall, reciprocal rank, or nDCG. Diversity metrics report unique canonical URLs, sources, domains, and the selected near-duplicate rate. Corroboration retention is a separate metric based on explicitly labeled high-scoring corroborators present in the score-order baseline; this makes evidence displacement visible instead of treating all similarity as undesirable duplication.

nDCG is normalized at the case's requested `top_k`, including when a restrictive policy returns fewer chunks, so selection shortfalls cannot receive a perfect score by shrinking the ideal ranking. All policies use descending score or adjusted utility with ascending chunk ID as the deterministic final tie-break.

The checked-in result is `docs/benchmarks/stage6-diversity-policy-results.json`. Latencies are deterministic fixture values, not observed production timings. Text novelty uses a simple token-set Jaccard model, identity fields are supplied by the fixture, and this small corpus does not establish a production policy. Live end-to-end diversity, canonicalization quality, near-duplicate thresholds, and answer effects remain untested.

## Stage 7 context-packing comparison

Stage 7 remains benchmark-only and models balanced context selection in memory. It does not import production packing code, call llama.cpp, or open a database. Run it with:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m benchmarks --stage 7
```

The replay compares Phase 1's eight-chunk, two-per-source, 12,000-character behavior; current balanced mode's 25-chunk, ten-source, three-per-source behavior; a relevance floor; marginal evidence-gain selection; explicit conflict/corroboration prioritization; caps of six, eight, and ten; and a combined candidate. Each individual mechanism is reported separately before the combined candidate.

Accuracy reports answer-bearing chunk precision, unique-evidence recall, answer readiness, conflict coverage, corroboration coverage, and no-answer abstention with explicit applicable-case counts. Corroborating chunks count consistently as relevant chunks for precision, while recall credits each required evidence identity once. Packing volume and unused budget are descriptive metrics, not accuracy objectives.

Current balanced chunk and source limits are derived per case from the applied token budget with the production formulas before any optional cap is applied. The token ceiling charges frozen fixed-payload and per-chunk rendering annotations in addition to evidence bodies. Phase 1's character ceiling likewise charges its question/topic framing, source headers, separators, instructions, and evidence bodies. These are deterministic fixture annotations: the replay does not claim to execute llama.cpp `/tokenize` or render the real payload.

The checked-in result is `docs/benchmarks/stage7-context-packing-results.json`. Generated noise tails make the 25-chunk baseline observable without storing repeated evidence text. Synthetic semantic annotations drive evidence-gain and relationship-aware policies, so those policies are evaluation models rather than deployable implementations. Live exact tokenization, rendering overhead, answer quality, conflict detection, corroboration detection, and threshold calibration remain untested.

The artifact derives its conservative fixture candidate by choosing the smallest evaluated cap whose cap-only mean evidence recall matches the best evaluated cap. That rule selects six on this corpus and is recorded with `production_decision: false`; it is not a production recommendation without broader and live evaluation.

## Stage 8 performance-policy comparison

Stage 8 remains benchmark-only and models performance mechanisms independently. It does not import production pipeline code, open a database, start a browser, call HTTP services, load embeddings, or contact llama.cpp. Run it with:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m benchmarks --stage 8
```

The replay compares per-attempt, per-operation, and scoped HTTP clients; per-URL and scoped ephemeral browser lifecycles; embedding every successful refresh versus skipping unchanged content; current fixed-point token counting plus a final call versus stopping on the exact call that validates the fixed point; and row-wise full sort, blockwise exact top-k, and vectorized matrix scan cost models at 1,000, 10,000, and 100,000 chunks.

Every family changes one modeled mechanism. Accuracy reports only fixture-observable outcome preservation. Reliability separately reports ownership and cleanup, actual fixture failures, absence of persistent profiles/cookies/credentials, active-content preservation, final exact token validation, and exact versus approximate vector behavior. Latency is deterministic arithmetic, not an observed speedup.

The checked-in result is `docs/benchmarks/stage8-performance-results.json`. Browser reuse assumes isolated page contexts inside one ephemeral browser; HTTP reuse assumes cookie and credential storage are disabled and lifecycle ownership is explicit. Token-count results use a synthetic fixed-point function. Exact vector top-k preservation is checked only on a small frozen score probe. Scale rows report preservation as `null`; their timings and retained-score counts are cost models, not accuracy, memory, or wall-clock measurements, and explicitly cannot justify a production optimization. All live lifecycle, cleanup, concurrency, tokenizer, embedding, database-scale vector, memory, and latency tests remain manual.

## Stage 9 configurable reranking comparison

Run `python -m benchmarks --stage 9`. The frozen offline corpus compares `off`, `heuristic`, and `cross_encoder` with identical questions, candidate pools, extraction assumptions, embedding assumptions, and selection limits. It reports MRR, nDCG@10, relevant- and duplicate-chunk ratios, citation support, an answer-correctness proxy, reranking latency, and total latency overall and for exact identifiers, semantic paraphrases, simple facts, complex comparisons, and ambiguous questions.

## Stage 10: production retrieval regression

Run `uv run python -m benchmarks --stage 10`. This opens an in-memory SQLite FTS5 fixture and calls the production safe-query builder and production rank-fusion helper. It records the corrected BM25 direction and controlled semantic/exact/dual-channel cases. The checked-in before audit is `docs/benchmarks/implementation-baseline-2026-08-01.json`; the after result is `docs/benchmarks/production-retrieval-results.json`.

The recorded result improved the controlled fusion mean reciprocal rank from `0.7778` to `1.0` and the FTS direction case from `0.5` to `1.0`. The measured `0.5301 ms` applies only to in-memory FTS plus fusion. It is not an end-to-end latency claim and excludes embeddings, CrossEncoder, network, browser, llama.cpp, and WebUI.

## Stage 11: research-mode limit policy

Run `uv run python -m benchmarks --stage 11`. This offline production-policy
benchmark records the effective request ceilings for `rapid`, `auto`, and
`deep` research. It checks conformance to the mode-specific page, source, and
chunk ceilings and reports request-bound violations and deterministic page-work
counts separately. Policy conformance changed from `5/9` fields to `9/9`, and
request-wide page-bound violations changed from one to zero. The combined
synthetic maximum page-attempt count across the three modes changed from 24 to
17. Progression contract violations changed from three to zero, covering
rapid-first behavior for complex queries and the three-page escalation ceiling.
They also cover staged evidence checks at two, five, and ten attempts for a
full deep pass. These are work bounds and control-flow checks, not measured
latency.

Staged stopping trades fewer browser attempts when evidence becomes sufficient
for up to three retrieval/reranking checks in a fully exhausted deep pass,
instead of one check at the end. The offline benchmark does not establish the
net wall-clock effect; that requires the manual live matrix.

The benchmark does not evaluate answer quality or execute SearXNG, Chromium,
embeddings, reranking, llama.cpp, or WebUI. The checked-in before and after
artifacts are `docs/benchmarks/research-mode-limits-before.json` and
`docs/benchmarks/research-mode-limits-results.json`.

## Stage 12: evidence-integrity policy

Run `uv run python -m benchmarks --stage 12`. This deterministic replay calls
the production access classifier, reranker candidate filter, and evidence
gate. Its versioned cases include 30 crawl-policy examples covering every
access outcome, legitimate long-form articles that discuss wall wording,
consent and navigation shells, dual-channel boilerplate,
a simple answer-bearing source, complex-query diversity, and a pool where bad
candidates must not be force-retained.

The checked-in before/result artifacts are
`docs/benchmarks/stage12-evidence-integrity-before.json` and
`docs/benchmarks/stage12-evidence-integrity-results.json`. On this fixture:

- the original five-case remediation changed crawl-outcome accuracy from `0.6` to `1.0`;
- the expanded classifier changed crawl-outcome accuracy from `0.8` to `1.0` and legitimate acceptance from `0.4` to `1.0`, removing six legitimate-article false positives;
- evidence-gate accuracy changed from `0.75` to `1.0` and false-sufficient decisions from one to zero;
- retained-candidate precision changed from `0.230769` to `1.0`, with known-bad retained candidates changing from ten to zero.

This small synthetic regression corpus establishes behavior only for its
listed mechanisms. It performs no network, browser, database, embedding,
CrossEncoder, llama.cpp, answer-model, or WebUI execution and reports no
wall-clock latency. Live results must be recorded separately.

## Stage 13: production stale-cache fallback

Run `uv run python -m benchmarks --stage 13`. This opens a disposable SQLite
database, stores one old usable source, injects a terminal refresh outcome, and
checks whether the prior evidence is associated with the new topic without
creating another active version. The before/result artifacts are
`docs/benchmarks/production-cache-before.json` and
`docs/benchmarks/production-cache-results.json`.

The stale evidence changed from unavailable to retrievable for the new topic;
the original topic remains retrievable, the terminal refresh outcome is
recorded, and exactly one active source version remains. The benchmark uses a
fixed test vector and performs no network, browser, embedding-model or
CrossEncoder work. Its operation count is descriptive, not wall-clock latency.

## Stage 14: evidence representation

Run `uv run python -m benchmarks --stage 14`. This lexical diagnostic compares
the former repeated security prefix with clean stored/embedded chunks and
render-time untrusted-evidence boundaries. The security boilerplate changes
from 15 indexed tokens per chunk to zero, while the rendered boundary remains.
The sample evidence-token share changes from `0.4444` to `1.0`, and 100 stored
characters per chunk are removed. These are representation diagnostics, not
sentence-transformer quality or latency claims. Existing non-empty databases
must be backed up and rebuilt because mixing the two embedding inputs would be
invalid.

## Stage 15: final packed-evidence assessment

Run `uv run python -m benchmarks --stage 15`. The deterministic cases compare
answerability decided from the pre-pack candidate set with reassessment of the
selection that survives source caps and token trimming. Answerability accuracy
changes from `0.5` to `1.0`, and false-answerable decisions change from two to
zero. The packed result preserves both the pre-pack and final assessments for
diagnostics and changes the stop reason to `packed_evidence_insufficient` when
trimming invalidates a previously sufficient result. This benchmark freezes
selection and does not call llama.cpp or an answer model.

## Stage 16: search-failure observability

Run `uv run python -m benchmarks --stage 16`. The deterministic policy cases
cover partial failure, total failure and a valid empty response. Outcome
accuracy changes from `0.3333` with silent failure handling to `1.0`: partial
results carry sanitized per-query statuses, total failure raises a typed error,
and a successful empty search remains distinct. The benchmark models outcomes;
retry latency still requires a synthetic local HTTP endpoint.

## Stage 17: crawl response policy

Run `uv run python -m benchmarks --stage 17`. Six synthetic CrawlResult cases
cover robots denial, 401, 404, empty success, CAPTCHA-on-403 and public success.
Outcome accuracy changes from `0.3333` with content-only classification to
`1.0` when response headers, status and crawler success are first-class.
`robots_denied`, `http_error`, `empty_content` and `extraction_failure` remain
distinct, and only transient timeout/connection/408/429/selected-5xx failures
are retryable. The benchmark does not execute Chromium or fetch robots.txt.

## Stage 18: canonical URL safety

Run `uv run python -m benchmarks --stage 18`. Four cases cover relative,
absolute, loopback and credential-bearing canonical links. Candidate-resolution
accuracy changes from `0.75` to `1.0`; production additionally performs the
same asynchronous public-network check used for crawl destinations before a
canonical URL can be stored or cited. The offline benchmark does not resolve
DNS, so redirect and rebinding behavior remains in the live matrix.

## Stage 19: freshness metadata

Run `uv run python -m benchmarks --stage 19`. Five date-extraction and four
query-window cases compare meta/time plus a fixed year filter with
provenance-aware JSON-LD/meta/time/search hints and derived day/month/year
windows. Date-provenance accuracy changes from `0.8` to `1.0`; window accuracy
changes from `0.5` to `1.0`. Dates later than the fetch time by more than one day
are rejected. These synthetic cases do not establish freshness-ranking gains;
that remains part of the human-judged live corpus.

## Stage 20: publication security surface

Run `uv run python -m benchmarks --stage 20`. Eight deterministic policy cases
cover the default MCP tool surface, loopback binding, trusted SearXNG endpoint
shape, redirect handling, URL-safe diagnostics and logging ownership. Control
coverage changes from `0.0` for the pre-publication surface to `1.0` for the
hardened policy. This is a control-presence benchmark, not a penetration test;
it opens no sockets and measures neither answer accuracy nor latency.

## Stage 21: remaining request deadline

Run `uv run python -m benchmarks --stage 21`. Four deterministic timing-policy
cases cover fast success, transient retry overrun, a slow first attempt and a
terminal failure. Outcome accuracy changes from `0.5` with operation timeouts
alone to `1.0` when each operation is capped by the remaining request deadline;
deadline compliance is `1.0`. Durations are fixture arithmetic. HTTP and
Chromium cancellation cleanup remains part of the live release matrix.

## Stage 22: page structure and answer contracts

Run `uv run python -m benchmarks --stage 22`. This deterministic production-policy
benchmark reproduces the observed schedule shape with synthetic content. It measures
orphaned section fragments, broken overlap starts, consent-marker removal, and
the availability of enforceable answer-transaction controls. It does not execute
a network request, browser, embedding model,
CrossEncoder, llama.cpp, or answer model. The before and after artifacts are
`docs/benchmarks/temporal-schedule-before.json` and
`docs/benchmarks/temporal-schedule-results.json`; interpretation and limitations
are recorded in `docs/benchmarks/temporal-schedule-analysis.md`.

## Metrics and interpretation

Scores and latency are deterministic fixture values; no real model, network, database, llama.cpp, or answer model runs. Peak memory is recorded as unavailable. The checked-in `docs/benchmarks/stage9-reranking-results.json` therefore validates comparison/reporting behavior only and is not a claim of live accuracy improvement.

The output keeps three metric families separate.

Accuracy includes search precision/recall, canonical-source and domain counts, relevant-page recall, answer-bearing chunk recall, chunk precision/recall, duplicate rate, source diversity, MRR, nDCG, packed-evidence precision, citation support, and a final-answer correctness proxy.

The final-answer metric is deliberately a deterministic selection-readiness proxy: it passes when all annotated answer-bearing chunks are selected. It is not an LLM answer evaluation and must not be reported as live answer accuracy.

Reliability includes classified crawl outcomes, partial-result rate, per-stage failures, known-good content preservation after a failed refresh, and llama detection/tokenization failure rates.

Latency includes operation counts and deterministic fixture duration p50/p95 values for cold and warm runs. Embedding initialization is counted once per cold benchmark process and never in the warm replay. These values validate reporting and expose relative operation counts; they are not live performance measurements.

Offline replay does not measure peak RSS and reports `peak_rss_bytes` as `null`. Peak memory must be collected by an isolated live benchmark process; the harness does not invent or compare pipeline-specific memory values.

Citation support is `null` for cases with no citation requirement. Such cases are excluded from aggregate citation support and are reported through `citation_support_applicable_cases`.

The benchmark-only `StageTracer` supports real monotonic wrapper timing for query planning, each search, merge/dedup, crawl/extraction, cleaning, chunking, embedding load/encode, database writes, FTS, vector scanning, normalization/fusion, diversity selection, rendering, `/props`, `/tokenize`, and total time. Production modules do not import the tracer.

## Deterministic tests

The tests block socket connection calls while offline replay runs, compare repeated outputs byte-for-byte as Python structures, verify disposable path restoration, validate all required metric families and stages, and assert that MCP signatures match the supported interface.

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest
```

## Live integration opt-in

The benchmark harness does not automate live integration execution. Supplying `--live` without both explicit acknowledgements fails before any network or browser action:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m benchmarks --live
```

The complete acknowledgement is:

```bash
AI_WEBSEARCH_BENCHMARK_ALLOW_LIVE=1 \
  UV_CACHE_DIR=/tmp/uv-cache \
  uv run python -m benchmarks --live --allow-live
```

Even with both acknowledgements, the harness stops and directs the operator to the manual matrix below. This prevents accidental access to services, credentials, cookies, profiles, or databases.

### Manual live matrix

Run these only in an isolated test environment with synthetic data and a disposable `AI_WEBSEARCH_DATABASE_PATH`:

1. SearXNG search response and retry timing.
2. Public Crawl4AI pages for success and synthetic consent/authentication/CAPTCHA/subscription/access-denied classifications.
3. Cold and warm local embedding load/encode timing.
4. Disposable SQLite FTS/vector retrieval at controlled corpus sizes.
5. llama.cpp `/props` validation and exact `/tokenize` operation counts.
6. End-to-end Phase 1 and current runs against the same frozen query set.

Do not use a personal or persistent browser profile, real cookies, credentials, browser storage, or a production database. CAPTCHA solving and paywall bypass are out of scope. Record the exact environment and report accuracy, reliability, and latency separately.

## Updating a baseline

Baseline/result updates require a corpus-version change or an intentional evaluation-protocol change. Generate the candidate under `/tmp`, review the full JSON diff, then update the checked-in artifact. Never overwrite a result as a side effect of a normal test run.
