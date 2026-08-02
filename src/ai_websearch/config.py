import ipaddress
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AI_WEBSEARCH_",
        extra="ignore",
    )

    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8050
    mcp_toolset: str = "answer"
    searxng_url: str = "http://127.0.0.1:8888"
    searxng_timeout_seconds: float = 15.0
    searxng_settings_path: str = "./searxng/settings.yml"
    database_path: str = "./data/ai_websearch.sqlite3"
    database_busy_timeout_seconds: float = 5.0

    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_model_revision: str = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
    embedding_device: str = "auto"
    embedding_batch_size: int = 32
    embedding_cache_folder: str = ""

    reranking_mode: str = "cross_encoder"
    reranking_model: str = "cross-encoder/ettin-reranker-17m-v1"
    reranking_model_revision: str = "9e4aa35321a6dd1a43ca313f500c4b4f7cfb5cc6"
    reranking_device: str = "auto"
    reranking_batch_size: int = 16
    reranking_max_length: int = 768
    reranking_candidates: int = 24
    reranking_cache_folder: str = ""

    scrape_timeout_seconds: float = 35.0
    max_chars_per_page: int = 60000
    user_agent: str = "Mozilla/5.0 (X11; Linux x86_64) ai-websearch/0.1.0b1"
    chunk_size_chars: int = 1200
    chunk_overlap_chars: int = 180
    min_chunk_chars: int = 180

    vector_weight: float = 0.70
    keyword_weight: float = 0.30

    llama_cpp_detection_mode: str = "auto"
    llama_cpp_base_url: str = ""
    llama_cpp_api_key: str = ""
    llama_cpp_model: str = ""
    llama_cpp_detection_cache_seconds: int = 300
    llama_cpp_request_timeout_seconds: float = 5.0
    llama_cpp_process_inspection_timeout_seconds: float = 3.0

    max_web_context_ratio: float = 0.60
    reserved_output_tokens: int = 4096
    reserved_system_tool_tokens: int = 4096
    reserved_history_tokens: int = 8192
    context_safety_margin_tokens: int = 2048

    default_research_mode: str = "auto"
    default_context_mode: str = "balanced"
    llama_cpp_local_only: bool = True

    rapid_research_max_seconds: float = 60.0
    deep_research_max_seconds: float = 240.0
    research_max_page_attempts_hard_limit: int = 20

    # Phase 5 uses these; harmless internal defaults in Phases 3–4.
    cache_ttl_hours: int = 24
    search_concurrency: int = 2
    search_min_interval_seconds: float = 0.5
    crawl_domain_concurrency: int = 1
    crawl_min_interval_seconds: float = 2.0
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0

    @field_validator("mcp_host")
    @classmethod
    def validate_mcp_host(cls, value: str) -> str:
        host = value.casefold().strip().strip("[]").rstrip(".")
        if host == "localhost":
            return value.strip()
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = False
        if not is_loopback:
            raise ValueError("AI_WEBSEARCH_MCP_HOST must be a loopback address")
        return value.strip()

    @field_validator("mcp_toolset")
    @classmethod
    def validate_mcp_toolset(cls, value: str) -> str:
        value = value.casefold().strip()
        if value not in {"answer", "diagnostic", "admin"}:
            raise ValueError("AI_WEBSEARCH_MCP_TOOLSET must be answer, diagnostic, or admin")
        return value

    @field_validator("searxng_url")
    @classmethod
    def validate_searxng_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "AI_WEBSEARCH_SEARXNG_URL must be an absolute HTTP(S) URL without credentials, query, or fragment"
            )
        host = parsed.hostname.casefold().rstrip(".")
        if host != "localhost":
            try:
                is_loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                is_loopback = False
            if not is_loopback:
                raise ValueError("AI_WEBSEARCH_SEARXNG_URL must use a loopback endpoint")
        return normalized

    @field_validator("embedding_device")
    @classmethod
    def validate_embedding_device(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in {"auto", "cpu", "cuda", "mps"}:
            raise ValueError("AI_WEBSEARCH_EMBEDDING_DEVICE must be auto, cpu, cuda, or mps")
        return value

    @field_validator("embedding_model_revision", "reranking_model_revision")
    @classmethod
    def validate_model_revision(cls, value: str) -> str:
        value = value.casefold().strip()
        if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("Model revisions must be full 40-character Git commit hashes")
        return value

    @field_validator("reranking_mode")
    @classmethod
    def validate_reranking_mode(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in {"off", "heuristic", "cross_encoder"}:
            raise ValueError("AI_WEBSEARCH_RERANKING_MODE must be off, heuristic, or cross_encoder")
        return value

    @field_validator("reranking_device")
    @classmethod
    def validate_reranking_device(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in {"auto", "cpu", "cuda"}:
            raise ValueError("AI_WEBSEARCH_RERANKING_DEVICE must be auto, cpu, or cuda")
        return value

    @field_validator("reranking_batch_size", "reranking_max_length", "reranking_candidates")
    @classmethod
    def validate_positive_reranking_integer(cls, value: int) -> int:
        if value <= 0:
            raise ValueError(
                "Reranking batch size, max length, and candidates must be positive integers"
            )
        return value

    @field_validator(
        "search_concurrency",
        "crawl_domain_concurrency",
        "max_retries",
    )
    @classmethod
    def validate_positive_network_integer(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Network concurrency and retry values must be positive integers")
        return value

    @field_validator("research_max_page_attempts_hard_limit")
    @classmethod
    def validate_research_page_hard_limit(cls, value: int) -> int:
        if not 1 <= value <= 20:
            raise ValueError(
                "AI_WEBSEARCH_RESEARCH_MAX_PAGE_ATTEMPTS_HARD_LIMIT must be between 1 and 20"
            )
        return value

    @field_validator(
        "database_busy_timeout_seconds",
        "search_min_interval_seconds",
        "crawl_min_interval_seconds",
        "retry_backoff_seconds",
    )
    @classmethod
    def validate_nonnegative_network_seconds(cls, value: float) -> float:
        if value < 0:
            raise ValueError("Timing values cannot be negative")
        return value

    @field_validator("llama_cpp_detection_mode")
    @classmethod
    def validate_detection_mode(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in {"auto", "manual"}:
            raise ValueError("AI_WEBSEARCH_LLAMA_CPP_DETECTION_MODE must be auto or manual")
        return value

    @field_validator("max_web_context_ratio")
    @classmethod
    def validate_ratio(cls, value: float) -> float:
        if not 0.05 <= value <= 0.90:
            raise ValueError("AI_WEBSEARCH_MAX_WEB_CONTEXT_RATIO must be between 0.05 and 0.90")
        return value

    @field_validator("default_research_mode")
    @classmethod
    def validate_research_mode(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in {"rapid", "deep", "auto"}:
            raise ValueError("AI_WEBSEARCH_DEFAULT_RESEARCH_MODE must be rapid, deep, or auto")
        return value

    @field_validator("default_context_mode")
    @classmethod
    def validate_context_mode(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in {"compact", "balanced", "evidence"}:
            raise ValueError(
                "AI_WEBSEARCH_DEFAULT_CONTEXT_MODE must be compact, balanced, or evidence"
            )
        return value

    @property
    def db_path(self) -> Path:
        path = Path(self.database_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def searxng_config_path(self) -> Path:
        return Path(self.searxng_settings_path).expanduser().resolve()

    @property
    def embedding_cache_path(self) -> str | None:
        return (
            str(Path(self.embedding_cache_folder).expanduser().resolve())
            if self.embedding_cache_folder.strip()
            else None
        )

    @property
    def embedding_model_identity(self) -> str:
        return f"{self.embedding_model}@{self.embedding_model_revision}"

    @property
    def reranking_cache_path(self) -> str | None:
        return (
            str(Path(self.reranking_cache_folder).expanduser().resolve())
            if self.reranking_cache_folder.strip()
            else None
        )

    @property
    def reserved_non_web_tokens(self) -> int:
        return (
            self.reserved_output_tokens
            + self.reserved_system_tool_tokens
            + self.reserved_history_tokens
            + self.context_safety_margin_tokens
        )


settings = Settings()
