# Stage 8 production decisions

The checked-in Stage 8 replay was recorded before these changes. Its synthetic
cases preserve request outcomes and exact final token counts while changing:

- SearXNG HTTP client instances: `6` per-attempt to `1` scoped client.
- Exact `/tokenize` calls: `15` with a redundant post-convergence validation to
  `12` by accepting the request that itself proves the fixed point.

Production now owns one ephemeral SearXNG client for a multi-query search pass
and one ephemeral llama.cpp client for a context-packing operation. Redirects,
response cookies are cleared after every call; persistent storage and
client-owned credentials remain absent. Redirects remain disabled. The
final serialized result is still validated exactly through llama.cpp
`/tokenize`; failure to stabilize within four exact validations is terminal.

SQLite connections now use a five-second busy timeout and run schema setup and
migrations once per database file identity per process. Foreign-key enforcement
is still configured on every connection.

Browser-process reuse, concurrent embedding serialization, and a production
dense-scan rewrite remain deferred. Stage 8 models those candidates but states
that its synthetic fixtures cannot justify production vector changes, and no
live Chromium/GPU/large-corpus timing was available for this change.
