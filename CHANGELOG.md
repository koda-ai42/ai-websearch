# Changelog

## Unreleased

## 0.1.0b1 (0.1.0 beta) — 2026-08-02

First public beta.

- Added section-aware Markdown chunking that preserves structured lists, prevents
  mid-word overlap fragments, and explicitly invalidates older embedding inputs.
- Removed high-confidence consent chrome and trailing navigation before
  chunking while preserving legitimate public article content.
- Strengthened the answer-agent contract with original-query, one-call,
  no-scope-expansion, citation, and exact fetched-date validation.
- Added a frozen page-structure regression benchmark with recorded before/after
  accuracy, reliability, and deterministic operation-count results.
- Added a local-first web research pipeline using SearXNG, ephemeral Chromium,
  SQLite FTS5, in-process Sentence Transformers embeddings, and a bounded local
  CrossEncoder reranker.
- Added bounded `rapid`, `auto`, and `deep` workflows with source diversity,
  duplicate suppression, evidence sufficiency checks, explicit stop reasons,
  and exact final llama.cpp `/tokenize` validation.
- Added automatic and manual llama-server discovery with `/props` as the sole
  source of the effective context size and without arbitrary port scanning or
  estimated context fallbacks.
- Added the `ai-websearch serve`, `doctor`, and `searxng` command surface plus a
  minimal default MCP process that exposes only `research`.
- Classified CAPTCHA, authentication, cookie-consent, subscription,
  robots-denied, access-denied, and HTTP-error responses as terminal,
  noncacheable outcomes. No interactive CAPTCHA handoff or bypass is included.
- Added 40 human-judgment queue cases and focused offline benchmarks for access
  classification, cache fallback, evidence representation, final packing,
  search failures, crawl responses, canonical URLs, freshness, security,
  deadlines, and performance decisions.
- Added explicit stale-if-error evidence reuse, final post-pack evidence
  reassessment, sanitized partial-search diagnostics, retry classification,
  robots checking, first-class HTTP outcomes, safe canonical URL handling, and
  publication-date provenance.
- Kept untrusted-content markers out of retrieval inputs and applied them only
  at the final context boundary.
- Restricted the default MCP process to `research`, hardened local endpoints
  and redirects, centralized safe URL/citation handling, and moved logging
  initialization to the executable boundary.
- Reused scoped service clients, added SQLite busy-timeout/lifecycle handling,
  enforced remaining request deadlines, and extracted typed research-pass
  state without changing MCP research tool names.
- Added GitHub publication documentation, notices, an SBOM, pinned SearXNG
  lifecycle scripts, CI/security automation, and release/history checks.
