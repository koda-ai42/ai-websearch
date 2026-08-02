from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    title: str = ""
    url: str
    content: str = ""
    engine: str | None = None
    engines: list[str] = Field(default_factory=list)
    score: float = 0.0
    published_at: str | None = None
    published_at_source: str | None = None


class ScrapedPage(BaseModel):
    url: str
    canonical_url: str | None = None
    title: str = ""
    markdown: str = ""
    fetched_at: str
    published_at: str | None = None
    published_at_source: str | None = None
    content_hash: str | None = None
    http_status: int | None = None
    success: bool
    outcome: str = "success"
    error: str | None = None


class IngestResult(BaseModel):
    ok: bool
    source_id: int | None = None
    url: str
    canonical_url: str | None = None
    title: str = ""
    topic: str | None = None
    fetched_at: str | None = None
    published_at: str | None = None
    published_at_source: str | None = None
    chunks_stored: int = 0
    content_hash: str | None = None
    http_status: int | None = None
    outcome: str = "success"
    cache_status: str = "miss"
    refresh_outcome: str | None = None
    error: str | None = None


class ContextChunk(BaseModel):
    chunk_id: int
    source_id: int
    url: str
    canonical_url: str | None = None
    title: str = ""
    topic: str | None = None
    fetched_at: str
    published_at: str | None = None
    published_at_source: str | None = None
    chunk_index: int
    text: str
    score: float
    vector_score: float = 0.0
    keyword_score: float = 0.0
    freshness_score: float | None = None
    vector_rank: int | None = None
    keyword_rank: int | None = None
    original_hybrid_score: float = 0.0
    original_hybrid_rank: int | None = None
    rerank_score: float | None = None
    rerank_reason: str | None = None
    pre_rerank_rank: int | None = None


class PackedChunkMetadata(BaseModel):
    chunk_id: int
    source_id: int
    score: float
    vector_score: float = 0.0
    keyword_score: float = 0.0
    freshness_score: float | None = None
    vector_rank: int | None = None
    keyword_rank: int | None = None
    original_hybrid_score: float = 0.0
    original_hybrid_rank: int | None = None
    rerank_score: float | None = None
    rerank_reason: str | None = None
    pre_rerank_rank: int | None = None


class PackedContext(BaseModel):
    query: str
    topic: str | None = None
    instructions: str
    llama_cpp: dict
    embedding: dict
    reranker: dict
    budget: dict
    research: dict
    context: str
    sources: list[dict]
    chunks: list[PackedChunkMetadata]
    warnings: list[str] = Field(default_factory=list)


def chunk_metadata(chunk: ContextChunk) -> PackedChunkMetadata:
    return PackedChunkMetadata(
        chunk_id=chunk.chunk_id,
        source_id=chunk.source_id,
        score=chunk.score,
        vector_score=chunk.vector_score,
        keyword_score=chunk.keyword_score,
        freshness_score=chunk.freshness_score,
        vector_rank=chunk.vector_rank,
        keyword_rank=chunk.keyword_rank,
        original_hybrid_score=chunk.original_hybrid_score,
        original_hybrid_rank=chunk.original_hybrid_rank,
        rerank_score=chunk.rerank_score,
        rerank_reason=chunk.rerank_reason,
        pre_rerank_rank=chunk.pre_rerank_rank,
    )
