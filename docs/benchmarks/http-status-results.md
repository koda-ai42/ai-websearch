# First-class HTTP status benchmark

Date: 2026-08-02

Change: expose an optional `http_status` on crawl and ingestion results and
preserve a terminal retryable HTTP status after bounded retries. Status remains
diagnostic; it cannot make failed content eligible for cache or retrieval.

The complete 21-stage offline harness was captured immediately before and after
the change. The raw SHA-256 values were:

- Before: `769bec3b3a67b3590894d51905ffd064b4f685901b9d5c9d40ae03565df2c8b2`
- After: `26e4a7b85dbace6dd505b2cfc6028033a409f22bfdbb2e1a380f6bbe37ae4901`

The only artifact difference was Stage 10's measured SQLite/fusion fixture time,
from 0.5317 ms to 0.5550 ms. Accuracy and reliability results are otherwise
byte-equivalent. The 0.0233 ms observation is noise-scale and does not support a
latency claim.

The non-live suite additionally verifies status type normalization, propagation
for terminal CAPTCHA and stale-fallback results, and preservation of transient
503 status metadata. Real HTTP crawling is reported separately in the live
release validation record.
