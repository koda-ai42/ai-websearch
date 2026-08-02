# Setup guide

## Host-native installation

The complete Python workflow can run on the Ubuntu host. Distrobox was previously used to supply Python/build/browser libraries, but it is not an architectural requirement.

```bash
./scripts/install_uv.sh
./scripts/setup_host.sh
cp .env.example .env
```

`setup_host.sh` runs `uv sync` and `uv run crawl4ai-setup`. Crawl4AI may request system-package installation for Chromium; review that prompt and install only the packages appropriate for the host. Distrobox remains an optional isolation choice through `scripts/create_distrobox.sh`, but no command requires it.

## Local services

Start the rootless, loopback-only SearXNG container from the host:

```bash
./scripts/start_searxng_podman.sh
```

The script creates the container once and restarts it on later calls. It passes a random `SEARXNG_SECRET` only when the container is created and mounts `searxng/settings.yml` read-only. SearXNG documents that this environment variable overrides `server.secret_key`: <https://docs.searxng.org/admin/settings/settings_server.html>.

The default image is pinned to a reviewed multi-architecture digest. It does
not float with `latest`. Inspect local state with
`./scripts/status_searxng_podman.sh`; update only after reviewing a new upstream
digest, then pass it explicitly to `./scripts/update_searxng_podman.sh`.

Start `llama-server` before the MCP service. Automatic detection inspects only visible processes, validates each candidate through `/props`, and exits on zero or multiple verified servers. It does not scan arbitrary ports or estimate a context size.

llama-server conventionally exposes its API and WebUI together on
`http://127.0.0.1:8080`. ai-websearch uses that port when a detected process has
no explicit `--port`; an explicit process flag or `LLAMA_ARG_PORT` remains
authoritative. For manual discovery, set
`AI_WEBSEARCH_LLAMA_CPP_BASE_URL=http://127.0.0.1:8080`.

```bash
uv run ai-websearch doctor
uv run ai-websearch doctor --search-probe
./scripts/start_mcp.sh
```

The default ai-websearch MCP endpoint is `http://127.0.0.1:8050/mcp`; it is
separate from llama-server/WebUI on port 8080. SearXNG is available only on the
loopback host at `http://127.0.0.1:8888`.

## Models

The default embedding model and CrossEncoder may download on first use. For a fully offline installation, pre-populate their configured cache folders or provide complete local model directories. Local model paths are never returned in MCP metadata.

An unavailable reranker device, incompatible model, corrupt files, or insufficient memory makes startup fail in `cross_encoder` mode. To use another mode, set `AI_WEBSEARCH_RERANKING_MODE=off` or `heuristic` and restart. The active request never falls back automatically.

Changing only reranker mode/model leaves the embedding database valid. Changing `AI_WEBSEARCH_EMBEDDING_MODEL` requires rebuilding the database; the service refuses to mix incompatible stored vectors.

## Engine administration

`uv run ai-websearch searxng engines list --all` reads the live `/config`
response. Enable/disable commands validate names against that response and
write only explicit `disabled` overrides. The official SearXNG settings merge
is documented at
<https://docs.searxng.org/admin/settings/settings.html#use-default-settings>.

## Validation boundaries

Offline tests mock external services. A successful unit suite does not prove Podman, Chromium, SearXNG upstream engines, model downloads, GPU inference, llama.cpp, or WebUI integration. Run the live doctor and the manual matrix in `VALIDATION.md` on the target host.
