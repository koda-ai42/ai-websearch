# Configuration reference

Settings are read from environment variables and `.env`. `.env.example` contains safe defaults.

## Services and storage

- `AI_WEBSEARCH_MCP_HOST`, `AI_WEBSEARCH_MCP_PORT`: MCP bind address and port. Non-loopback binds are rejected because the service has no application-layer authentication.
- `AI_WEBSEARCH_MCP_TOOLSET`: `answer` (only `research`), `diagnostic`, or `admin`. Prefer a one-process override such as `ai-websearch serve --toolset diagnostic` instead of a persistent elevation.
- `AI_WEBSEARCH_SEARXNG_URL`, `AI_WEBSEARCH_SEARXNG_TIMEOUT_SECONDS`, `AI_WEBSEARCH_SEARXNG_SETTINGS_PATH`: loopback SearXNG endpoint (default `http://127.0.0.1:8888`), timeout, and the YAML file changed by engine administration. Credentials, query strings, fragments, and non-loopback hosts are rejected.
- `AI_WEBSEARCH_DATABASE_PATH`: SQLite evidence database. New databases are created mode `0600`.
- `AI_WEBSEARCH_DATABASE_BUSY_TIMEOUT_SECONDS`: bounded wait for concurrent SQLite writers; default `5` seconds.
- `AI_WEBSEARCH_LLAMA_CPP_LOCAL_ONLY`: when true, llama.cpp endpoints must be loopback addresses.

## Embeddings and reranking

- `AI_WEBSEARCH_EMBEDDING_MODEL`, `AI_WEBSEARCH_EMBEDDING_MODEL_REVISION`,
  `AI_WEBSEARCH_EMBEDDING_DEVICE`, `AI_WEBSEARCH_EMBEDDING_BATCH_SIZE`,
  `AI_WEBSEARCH_EMBEDDING_CACHE_FOLDER`: in-process sentence-transformer
  embedding settings. The revision must be a full immutable Git commit hash and
  is part of database compatibility metadata.
- `AI_WEBSEARCH_RERANKING_MODE`: `off`, `heuristic`, or `cross_encoder`; default `cross_encoder`.
- `AI_WEBSEARCH_RERANKING_MODEL`, `AI_WEBSEARCH_RERANKING_MODEL_REVISION`,
  `AI_WEBSEARCH_RERANKING_DEVICE`, `AI_WEBSEARCH_RERANKING_BATCH_SIZE`,
  `AI_WEBSEARCH_RERANKING_MAX_LENGTH`, `AI_WEBSEARCH_RERANKING_CANDIDATES`,
  `AI_WEBSEARCH_RERANKING_CACHE_FOLDER`: bounded CrossEncoder settings. The
  revision must be a full immutable Git commit hash.

There is no fallback between reranking modes. A mode/model/revision change
requires restart but does not invalidate embeddings. An embedding model or
revision change requires rebuilding the database.

## Agentic research

- `AI_WEBSEARCH_DEFAULT_RESEARCH_MODE`: `rapid`, `deep`, or `auto`.
- `AI_WEBSEARCH_RAPID_RESEARCH_MAX_SECONDS`, `AI_WEBSEARCH_DEEP_RESEARCH_MAX_SECONDS`: soft wall-clock budgets. Individual already-started network/model calls remain governed by their own shorter timeouts.
- `AI_WEBSEARCH_RESEARCH_MAX_PAGE_ATTEMPTS_HARD_LIMIT`: administrator-controlled absolute ceiling applied after the mode default and caller ceiling; default `20`.
- `AI_WEBSEARCH_DEFAULT_CONTEXT_MODE`: `compact`, `balanced`, or `evidence`.

Automatic freshness uses a day window for “today/now”, a month window for
recent/month wording, and a year window for other current/latest queries.
Explicit `day`, `month`, or `year` values remain authoritative. Page-derived
JSON-LD/meta/time dates take precedence over SearXNG date hints, and the
provenance is returned with each source.

The mode defaults are `rapid=2/2/8`, `auto=5/5/15`, and `deep=10/8/24` for
page attempts, packed sources, and packed chunks respectively. The optional MCP
parameters default to `None`, meaning that these mode defaults apply. Explicit
values can only tighten them. Context budget and CrossEncoder bounds are applied
afterward and may lower source or chunk limits further.

`auto` performs at most one rapid pass and one escalation, sharing its five-page
allowance across both. The evidence gate considers usable chunks, query-term
coverage, dual-channel retrieval, source diversity, and the final packer's
source/chunk limits. Low coverage cannot be overridden by one source merely
because both FTS and dense retrieval selected it.
`retrieve_context` has no categorical depth setting and does not crawl; use its
numeric `top_k`, `max_sources`, and `max_chunks` parameters instead.

For example, `research(mode="deep", max_page_attempts=5)` retains deep query
planning and evidence evaluation but processes at most five distinct URL
candidates. The result exposes the resolution chain under `research.limits`:

```json
{
  "mode_defaults": {"max_page_attempts": 10, "max_sources": 8, "max_chunks": 24},
  "requested": {"max_page_attempts": 5},
  "effective": {"max_page_attempts": 5, "max_sources": 8, "max_chunks": 24},
  "absolute_max_page_attempts": 20
}
```

## Search, crawling, and cache

- `AI_WEBSEARCH_SEARCH_CONCURRENCY`, `AI_WEBSEARCH_SEARCH_MIN_INTERVAL_SECONDS`: shared pacing for calls to the configured SearXNG host.
- `AI_WEBSEARCH_CRAWL_DOMAIN_CONCURRENCY`, `AI_WEBSEARCH_CRAWL_MIN_INTERVAL_SECONDS`: shared per-target-domain crawl pacing.
- `AI_WEBSEARCH_MAX_RETRIES`, `AI_WEBSEARCH_RETRY_BACKOFF_SECONDS`: finite retry policy. Classified access walls are not retried.
- `AI_WEBSEARCH_SCRAPE_TIMEOUT_SECONDS`, `AI_WEBSEARCH_MAX_CHARS_PER_PAGE`, `AI_WEBSEARCH_USER_AGENT`: crawl bounds.
- `AI_WEBSEARCH_CACHE_TTL_HOURS`: fresh-cache reuse window. Unchanged content reuses embeddings; changed versions retain history with exactly one active version.

The local SearXNG limiter remains disabled because it requires Valkey; request pacing is applied in this service instead. SearXNG is bound to loopback.

Content-quality policy version 2 has no tunable threshold in configuration. This keeps
crawl, cache, retrieval, and evidence-gate eligibility consistent. Audit
existing sources before applying the versioned policy:

```bash
uv run ai-websearch cache audit --json
uv run ai-websearch cache audit --apply --json
```

The first command is read-only apart from any required database schema
migration; the second records usable classifications and quarantines unusable
sources without deleting their versions.

Section-aware chunking and consent cleanup change the embedding input identity
to `clean_sections_v3`. Back up and rebuild any non-empty evidence database made
with an earlier input version; startup fails explicitly instead of mixing old
and new vectors.

Answer clients can inspect their integration requirements with
`uv run ai-websearch agent-contract --json`. The default server publishes only
`research`. Run a separate, short-lived `--toolset diagnostic` or `--toolset
admin` process when the stable low-level tools are required; do not connect an
answer agent to that elevated process. The client must send the original query
unchanged, call `research` exactly once, avoid unrequested related claims, and
validate the final citation and exact fetched date.

## llama.cpp context safety

- `AI_WEBSEARCH_LLAMA_CPP_DETECTION_MODE`: `auto` or `manual`.
- `AI_WEBSEARCH_LLAMA_CPP_BASE_URL`: required only in manual mode; the conventional llama-server/WebUI endpoint is `http://127.0.0.1:8080`, and credentials and query parameters are rejected.
- `AI_WEBSEARCH_LLAMA_CPP_API_KEY`, `AI_WEBSEARCH_LLAMA_CPP_MODEL`: optional authentication/routing values; never returned or logged.
- `AI_WEBSEARCH_LLAMA_CPP_DETECTION_CACHE_SECONDS`, `AI_WEBSEARCH_LLAMA_CPP_REQUEST_TIMEOUT_SECONDS`, `AI_WEBSEARCH_LLAMA_CPP_PROCESS_INSPECTION_TIMEOUT_SECONDS`: bounded discovery and request timing.
- `AI_WEBSEARCH_MAX_WEB_CONTEXT_RATIO` and the reservation variables determine the upper evidence budget.

The effective context always comes from `/props`. The final full MCP result is counted with `/tokenize`; there is no configured or estimated fallback context size.

## URL policy

`config/url_policy.yml` is an optional local denylist. It blocks exact domains and subdomains. URL eligibility is a binary security/policy decision, never a relevance or authority score.
