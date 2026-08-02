# ai-websearch rename benchmark

Recorded 2026-08-02 before and after the mechanical pre-release rename.

| Benchmark | Accuracy/reliability result | Deterministic output |
|---|---|---|
| Stage 1 offline pipeline | unchanged | byte-identical |
| Stage 10 production retrieval | unchanged | latency-only delta |
| Stage 11 research bounds | unchanged | byte-identical |
| Stage 12 evidence integrity | unchanged | byte-identical |

Stage 10's in-memory SQLite-plus-fusion timing changed from `0.5215 ms` to
`0.5896 ms` (`+0.0681 ms`). This sub-millisecond single-run variation is not an
end-to-end latency regression; embeddings, reranking, network, browser,
llama.cpp and UI work are excluded. No retrieval, ranking, crawl, cache,
packing, llama discovery or tokenization behavior changed in the rename.

The non-live test suite increased from 165 to 167 tests because the consolidated
CLI gained parser and SearXNG-status coverage.
