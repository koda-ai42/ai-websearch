from __future__ import annotations

from typing import Any


class AiWebsearchError(RuntimeError):
    code = "ai_websearch_error"

    def __init__(self, message: str, *, details: Any = None, resolution: Any = None):
        super().__init__(message)
        self.message = message
        self.details = details
        self.resolution = resolution

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"error": self.code, "message": self.message}
        if self.details is not None:
            payload["details"] = self.details
        if self.resolution is not None:
            payload["resolution"] = self.resolution
        return payload


class EmbeddingModelMismatchError(AiWebsearchError):
    code = "embedding_model_mismatch"


class LlamaServerNotFoundError(AiWebsearchError):
    code = "llama_server_not_found"


class MultipleLlamaServersError(AiWebsearchError):
    code = "multiple_llama_servers"


class LlamaAuthenticationError(AiWebsearchError):
    code = "llama_server_authentication_failed"


class LlamaVerificationError(AiWebsearchError):
    code = "llama_server_verification_failed"


class ContextBudgetError(AiWebsearchError):
    code = "context_budget_error"


class TokenCountError(AiWebsearchError):
    code = "token_count_failed"


class RerankerInitializationError(AiWebsearchError):
    code = "reranker_initialization_failed"


class RerankingError(AiWebsearchError):
    code = "reranking_failed"


class HeuristicRerankingError(RerankingError):
    code = "heuristic_reranking_failed"


class RerankingScoreCountError(RerankingError):
    code = "reranking_score_count_mismatch"


class InvalidRerankingScoreError(RerankingError):
    code = "invalid_reranking_score"


class InvalidRerankingCandidateConfigurationError(AiWebsearchError):
    code = "invalid_reranking_candidate_configuration"


class FtsQueryError(AiWebsearchError):
    code = "fts_query_failed"


class SearchUnavailableError(AiWebsearchError):
    code = "search_unavailable"
