# Immutable model revision benchmark

Date: 2026-08-02

Change: pin the default embedding and CrossEncoder model identifiers to full
Hugging Face Git revisions, pass those revisions to Sentence Transformers, and
include the embedding revision in database compatibility metadata.

## Method

The complete offline harness (`python -m benchmarks --all`) was captured before
and after the production configuration change. The raw artifacts were 402,248
bytes each. Their SHA-256 values differ only because Stage 10 records a real
sub-millisecond SQLite/fusion duration:

| Run | Raw SHA-256 | Stage 10 fixture time |
| --- | --- | ---: |
| Before | `847af13c47625d16d32ee85d743d99858088a73e8aa853434a4411dd60ca633d` | 0.5156 ms |
| After | `ef69d8734897ea3015fcf7f94be5e0e4e85c7a730d78b1b69a9d1f3cc745a751` | 0.5518 ms |

After replacing every `*_ms` observation with a fixed marker, both complete
artifacts have SHA-256
`8167b64f87a34b1f831ad04f462a4de45af6f52edf5d94c2cebdcfe5a5897514`.

## Result

- Accuracy: every fixture-observable result is byte-equivalent after timing is
  normalized.
- Reliability: every offline invariant and failure classification is
  byte-equivalent. Embedding revision changes now fail closed against a
  nonempty incompatible database.
- Latency: the one observed in-process fixture changed by 0.0362 ms. This is
  noise-scale and does not support a speed claim.

Real model download, startup, CPU/GPU inference, memory, and retrieval quality
were not exercised by this offline comparison and remain live release gates.
