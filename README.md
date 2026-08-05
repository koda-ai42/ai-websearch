# AI Websearch

> 0.1.0 beta: interfaces and storage migrations may still change before 1.0.

AI Websearch is a local-first web RAG and research MCP server for llama.cpp and
local LLM frontends. 

It bridges the gap between your offline models and real-time information by 
querying a loopback SearXNG instance, securely crawling public web pages via 
an ephemeral browser, and locally retrieving and reranking the most relevant 
evidence. **The result? High-quality, citation-ready context delivered straight 
to your LLM—with zero data leaks to external APIs.**

AI Websearch performs retrieval and context preparation; it does not host or
invoke the answer-generating model. llama.cpp provides context discovery and
exact tokenization, while the connected LLM produces the final answer.

```text
question -> SearXNG -> public pages -> clean/chunk -> FTS5 + local embeddings
         -> bounded CrossEncoder -> diverse evidence pack -> llama.cpp /tokenize
```

Embeddings, reranking, retrieval, and the SQLite evidence cache run locally.
Search queries are sent to the SearXNG engines you enable, and crawling makes
ordinary network requests to public pages. No hosted LLM or external embedding
service is required.

## Requirements

The maintained development environment is Ubuntu 26.04 LTS with Python 3.11+
and [`uv`](https://docs.astral.sh/uv/). Rootless Podman runs SearXNG. Crawl4AI's
Chromium setup is required for crawling, and a running `llama-server` is
required for context discovery and exact final token validation. Distrobox is
optional.

The offline suite also runs on GitHub's Ubuntu workers. Podman, Chromium,
upstream search engines, model inference, llama.cpp, and llama-ui need separate
live validation on the target host.

## Quick start

Clone this repository, then run:

```bash
cd ai-websearch
uv sync --frozen
uv run crawl4ai-setup
cp .env.example .env
./scripts/start_searxng_podman.sh
uv run ai-websearch doctor --search-probe
uv run ai-websearch serve
```

The MCP endpoint is `http://127.0.0.1:8050/mcp`. Add it to a llama.cpp-compatible
frontend as a Streamable HTTP MCP server. Tool-capable llama.cpp templates may
also require `llama-server --jinja`; use the flags appropriate for the selected
model and frontend.

AI Websearch detects visible `llama-server` processes and verifies candidates
through `/props`; it never scans arbitrary ports. `/props` is the only source
of effective `n_ctx`, and `/tokenize` validates the complete final result. For
a server that cannot be discovered safely, configure it explicitly:

```env
AI_WEBSEARCH_LLAMA_CPP_DETECTION_MODE=manual
AI_WEBSEARCH_LLAMA_CPP_BASE_URL=http://127.0.0.1:8080
```

Port 8080 is llama-server's conventional combined API/WebUI endpoint. The
AI Websearch MCP endpoint remains separate on port 8050.

Useful commands:

```bash
uv run ai-websearch --help
uv run ai-websearch doctor
uv run ai-websearch serve
uv run ai-websearch serve --toolset diagnostic
uv run ai-websearch searxng status
uv run ai-websearch agent-contract --json
```

The default MCP process exposes only `research`. Diagnostic and administrative
tools retain stable names but are available only from an explicitly elevated
process. Do not connect a general answer agent to an elevated process. Answer
clients must send the original question unchanged, call `research` exactly
once, avoid unrequested scope expansion, and include a provided citation plus
its exact fetched date.

## Research modes

The `research` MCP tool accepts three bounded modes:

| Mode | Intended use | Page attempts | Packed sources | Packed chunks |
| --- | --- | ---: | ---: | ---: |
| `rapid` | Straightforward lookup | 2 | 2 | 8 |
| `auto` | Rapid, then at most one evidence-driven escalation | 5 | 5 | 15 |
| `deep` | Comparison or multi-source synthesis | 10 | 8 | 24 |

These are ceilings, not targets. Explicit MCP limits can tighten but never
expand them. `auto` shares its five-page allowance across both passes. Every
result reports the evidence assessment, answerability, stop reason, resolved
limits, and sanitized search diagnostics.

Retrieval uses SQLite FTS5 plus in-process Sentence Transformers embeddings.
The default bounded CrossEncoder reranker has no automatic fallback; select
`off`, `heuristic`, or `cross_encoder` explicitly. Original hybrid scores and
ranks remain available for diagnostics. Source diversity and duplicate
suppression are applied before final packing.

## SearXNG

The repository distributes SearXNG configuration and rootless Podman lifecycle
scripts, not SearXNG source code, container layers, or persistent state. The
start script pulls a reviewed official image digest and maps SearXNG's internal
port 8080 to the loopback host endpoint `127.0.0.1:8888`.

```bash
./scripts/start_searxng_podman.sh
./scripts/status_searxng_podman.sh
uv run ai-websearch searxng status
uv run ai-websearch searxng engines list --all
uv run ai-websearch searxng engines disable "google" --restart
./scripts/stop_searxng_podman.sh
```

Updating is an explicit review step. Copy a reviewed
`docker.io/searxng/searxng@sha256:...` reference from the upstream registry,
then recreate the stateless container:

```bash
AI_WEBSEARCH_SEARXNG_IMAGE='docker.io/searxng/searxng@sha256:REVIEWED_DIGEST' \
  ./scripts/update_searxng_podman.sh
```

Engine requests still leave the machine through the enabled upstream engines.
Read [SearXNG's settings documentation](https://docs.searxng.org/admin/settings/settings.html)
before changing `searxng/settings.yml`.

## Models and local storage

The default models are:

- Embeddings: `sentence-transformers/all-MiniLM-L6-v2` at
  `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`
- Reranking: `cross-encoder/ettin-reranker-17m-v1` at
  `9e4aa35321a6dd1a43ca313f500c4b4f7cfb5cc6`

They download on first use unless already cached. Disk and peak RAM use depend
on the selected revisions, device, batch sizes, and runtime; validate them on
the target system. Both defaults are primarily English-focused. MiniLM's model
card documents truncation beyond 256 word pieces, so chunk effectiveness is
measured by the benchmark suite rather than inferred from character length.

Changing the reranker mode, model, or revision does not invalidate the embedding
database. Changing the embedding model, revision, or stored chunk representation
requires rebuilding it; AI Websearch refuses to mix incompatible stored vectors.
Section-aware chunks use input version `clean_sections_v3`. The default database
`data/ai_websearch.sqlite3`.

## Security and access boundaries

AI Websearch is designed for one trusted local user:

- MCP, SearXNG, and llama.cpp endpoints are loopback-only by default.
- Only public HTTP(S) pages are crawled; private-network and credential-bearing
  targets are rejected before browser navigation and again after redirects.
- Browser contexts are headless, ephemeral, read-only, and do not use personal
  profiles, persistent cookies, browser storage, or downloads.
- CAPTCHA, authentication, cookie-consent, subscription, robots-denied,
  access-denied, and HTTP-error pages are classified as failed outcomes. They
  are not cached, embedded, ranked, bypassed, or handed to a user for action.
- Retrieved text is untrusted evidence. Injection detection is advisory; the
  durable controls are instruction/evidence separation, URL/output sanitation,
  and a minimal MCP tool surface.
- A failed refresh cannot replace known-good cached content; eligible stale
  evidence may be returned explicitly as `stale_fallback`.

Do not expose this unauthenticated service on a network. See
[SECURITY.md](SECURITY.md) for reporting and deployment assumptions.

## Validation

```bash
uv sync --frozen --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run python -m compileall src tests
uv run pytest -q -m 'not live'
bash -n scripts/*.sh
UV_CACHE_DIR=/tmp/ai-websearch-uv-cache ./scripts/smoke_test.sh
uv build --no-sources
uv run python scripts/check_release.py --artifacts dist
uv run python scripts/generate_sbom.py
```

Offline tests use synthetic or mocked external services. They do not establish
that Podman, Chromium, SearXNG upstream engines, model downloads/inference,
llama.cpp, or llama-ui work on a particular host. The live release matrix is in
[VALIDATION.md](VALIDATION.md), and recorded benchmark results are under
[`docs/benchmarks/`](docs/benchmarks/).
The latest workstation-specific live matrix is recorded in
[`publication-live-validation-2026-08-02.md`](docs/benchmarks/publication-live-validation-2026-08-02.md).

Troubleshooting and configuration details are in the
[setup guide](docs/SETUP.md), [configuration reference](docs/CONFIGURATION.md),
[architecture](docs/ARCHITECTURE.md), and
[benchmark guide](docs/BENCHMARKING.md).

## Contributing and license

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) before changing
retrieval or crawling behavior. Authored project code is available under the
[MIT License](LICENSE). Dependencies, model weights, and the separately operated
SearXNG service retain their own licenses; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and the checked-in CycloneDX
SBOM.

This product includes software developed by UncleCode
(https://x.com/unclecode) as part of the Crawl4AI project
(https://github.com/unclecode/crawl4ai).
