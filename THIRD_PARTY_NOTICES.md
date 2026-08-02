# Third-party notices

ai-websearch's MIT license covers the code authored in this repository. It does
not replace the licenses of dependencies, model weights, or separately operated
services. The CycloneDX SBOM records the resolved Python dependency graph; the
notices below call out important runtime components.

## Crawl4AI

[Crawl4AI](https://github.com/unclecode/crawl4ai) is licensed under the
[Apache License 2.0](https://github.com/unclecode/crawl4ai/blob/main/LICENSE).

This product includes software developed by UncleCode
(https://x.com/unclecode) as part of the Crawl4AI project
(https://github.com/unclecode/crawl4ai).

## Sentence Transformers and FastMCP

[Sentence Transformers](https://github.com/huggingface/sentence-transformers)
and [FastMCP](https://github.com/jlowin/fastmcp) are distributed under the
Apache License 2.0. Their transitive dependencies retain their own licenses.

## SearXNG

[SearXNG](https://github.com/searxng/searxng) is licensed under AGPL-3.0-or-later.
This repository provides configuration and scripts that pull an unmodified,
official OCI image as a separately operated loopback service. It does not
redistribute SearXNG source, container layers, or persistent service state.
The corresponding source and license are available from the upstream project.

## llama.cpp

[llama.cpp](https://github.com/ggml-org/llama.cpp) is an external service and is
distributed under the MIT License. It is not bundled by ai-websearch.

## Model weights

Model weights are downloaded separately and are not covered by this project's
MIT license. Review the license and usage terms for the exact revision selected:

- [`sentence-transformers/all-MiniLM-L6-v2`](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/tree/1110a243fdf4706b3f48f1d95db1a4f5529b4d41)
- [`cross-encoder/ettin-reranker-17m-v1`](https://huggingface.co/cross-encoder/ettin-reranker-17m-v1/tree/9e4aa35321a6dd1a43ca313f500c4b4f7cfb5cc6)

This notice is an engineering inventory, not legal advice.
