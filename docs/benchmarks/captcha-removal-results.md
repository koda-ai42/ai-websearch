# CAPTCHA handoff removal benchmark

Recorded 2026-08-02 before and after removal of interactive CAPTCHA handling.

| Benchmark | Accuracy | Reliability | Synthetic latency |
|---|---|---|---|
| Stage 3 crawl/extraction | unchanged | unchanged | unchanged |
| Stage 4 cache policy | unchanged | unchanged | unchanged |
| Stage 12 evidence integrity | unchanged | unchanged | unchanged |

All three JSON results were byte-identical. CAPTCHA remains a distinct terminal
access outcome and remains ineligible for caching, embedding and retrieval. The
visible-browser wait and second interactive crawl were removed. Default headless
crawl latency is unchanged in these offline models; removal eliminates the
optional 120-second human wait path.
