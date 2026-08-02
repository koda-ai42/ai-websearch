# Page-structure remediation benchmark

The frozen Stage 22 corpus models the observed France schedule page with
synthetic text. The unchanged production baseline is recorded in
`temporal-schedule-before.json`; the remediated policy is recorded in
`temporal-schedule-results.json`.

## Accuracy

- Section-boundary accuracy improves from `0.0` to `1.0` across two structural
  checks.

## Reliability

- Broken chunk starts decrease from one to zero.
- Orphaned section fragments decrease from one to zero.
- Four consent markers decrease to zero while the public article remains.
- Original-query, citation/fetch-date, no-scope-expansion, and
  transaction-validator controls change from absent to present.

## Latency and work

Stage 22 performs no wall-clock latency measurement. It produces three chunks
before and after, so it demonstrates no deterministic chunk-count regression.
The captured live example spent about 4.5 seconds per research call and made two
calls; the one-call contract would avoid the duplicate call, but no remediated
live timing is claimed here.

## Limitations

- The fixture is synthetic and covers one observed page shape.
- A consuming answer integration must call `validate_answer_transaction`; the
  MCP evidence server cannot intercept text produced by an external model.
- Existing non-empty evidence databases must be backed up and rebuilt for
  embedding input version `clean_sections_v3`.
- Podman, Chromium, SearXNG upstream search, embedding/CrossEncoder inference,
  llama.cpp, and WebUI integration were not exercised by this offline benchmark.
