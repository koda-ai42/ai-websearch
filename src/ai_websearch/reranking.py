from __future__ import annotations

import asyncio
import math
from collections.abc import Callable, Sequence
from functools import cmp_to_key
from typing import Any

from .config import settings
from .errors import (
    HeuristicRerankingError,
    InvalidRerankingScoreError,
    RerankerInitializationError,
    RerankingError,
    RerankingScoreCountError,
)
from .models import ContextChunk
from .security import safe_model_label

TIE_TOLERANCE = 1e-6


def candidate_passage(candidate: ContextChunk) -> str:
    # Chunking does not currently retain a separate section path.
    return "\n".join(part for part in (candidate.title.strip(), candidate.text.strip()) if part)


def heuristic_score(candidate: ContextChunk) -> float:
    """Expose the legacy lightweight fused score as an explicit rerank score."""
    return candidate.score


class RerankerService:
    def __init__(
        self,
        model_factory: Callable[..., Any] | None = None,
        heuristic: Callable[[ContextChunk], float] = heuristic_score,
    ):
        self._model_factory = model_factory
        self._heuristic = heuristic
        self._model: Any = None
        self._load_lock = asyncio.Lock()
        self._inference_lock = asyncio.Lock()

    async def initialize(self) -> None:
        if settings.reranking_mode != "cross_encoder":
            return
        if self._model is not None:
            return
        async with self._load_lock:
            if self._model is not None:
                return
            try:
                factory = self._model_factory
                if factory is None:
                    from sentence_transformers import CrossEncoder

                    factory = CrossEncoder
                kwargs: dict[str, Any] = {"max_length": settings.reranking_max_length}
                kwargs["revision"] = settings.reranking_model_revision
                if settings.reranking_device != "auto":
                    kwargs["device"] = settings.reranking_device
                if settings.reranking_cache_path:
                    kwargs["cache_folder"] = settings.reranking_cache_path
                if self._model_factory is not None:
                    # Injected factories are deterministic test/local adapters and
                    # need no worker hand-off. Production model loading remains off-loop.
                    self._model = factory(settings.reranking_model, **kwargs)
                else:
                    self._model = await asyncio.to_thread(
                        factory, settings.reranking_model, **kwargs
                    )
            except Exception as exc:
                raise RerankerInitializationError(
                    "The configured CrossEncoder reranker could not be initialized.",
                    details={"model": safe_model_label(settings.reranking_model)},
                    resolution="Verify the model identifier or local directory, cache path, device configuration and available memory.",
                ) from exc

    async def rank(
        self, query: str, candidates: list[ContextChunk], limit: int
    ) -> tuple[list[ContextChunk], dict]:
        mode = settings.reranking_mode
        received = len(candidates)
        if mode == "off":
            return candidates, self.metadata(received, 0)
        if mode == "heuristic":
            try:
                scores = [float(self._heuristic(candidate)) for candidate in candidates]
                self._validate(scores, received)
            except RerankingError:
                raise
            except Exception as exc:
                raise HeuristicRerankingError(
                    "Heuristic reranking failed.",
                    details={"mode": "heuristic"},
                    resolution="Check the heuristic reranker configuration or explicitly configure AI_WEBSEARCH_RERANKING_MODE=off and restart.",
                ) from exc
            return self._ordered(candidates, scores, "heuristic"), self.metadata(received, received)

        await self.initialize()
        scored = candidates[:limit]
        if not scored:
            return [], self.metadata(received, 0)
        pairs = [(query, candidate_passage(candidate)) for candidate in scored]
        try:
            async with self._inference_lock:
                if self._model_factory is not None:
                    raw = self._model.predict(
                        pairs,
                        batch_size=settings.reranking_batch_size,
                        show_progress_bar=False,
                    )
                else:
                    raw = await asyncio.to_thread(
                        self._model.predict,
                        pairs,
                        batch_size=settings.reranking_batch_size,
                        show_progress_bar=False,
                    )
            scores = _flatten_scores(raw)
            self._validate(scores, len(scored))
        except RerankingError:
            raise
        except Exception as exc:
            raise RerankingError(
                "CrossEncoder reranking failed.",
                details={"mode": "cross_encoder"},
                resolution="Check the configured model, device and available memory, or explicitly configure AI_WEBSEARCH_RERANKING_MODE=off and restart.",
            ) from exc
        return self._ordered(scored, scores, "cross_encoder"), self.metadata(received, len(scored))

    @staticmethod
    def _validate(scores: Sequence[float], expected: int) -> None:
        if len(scores) != expected:
            raise RerankingScoreCountError(
                "Reranker score count did not match the candidate count.",
                details={"expected": expected, "received": len(scores)},
            )
        if any(not math.isfinite(score) for score in scores):
            raise InvalidRerankingScoreError("Reranker returned a non-finite score.")

    @staticmethod
    def _ordered(
        candidates: list[ContextChunk], scores: Sequence[float], reason: str
    ) -> list[ContextChunk]:
        updated = [
            candidate.model_copy(update={"rerank_score": score, "rerank_reason": reason})
            for candidate, score in zip(candidates, scores)
        ]

        def compare(left: ContextChunk, right: ContextChunk) -> int:
            if left.rerank_score is None or right.rerank_score is None:
                raise InvalidRerankingScoreError("Reranker score was unexpectedly absent.")
            difference = left.rerank_score - right.rerank_score
            if abs(difference) > TIE_TOLERANCE:
                return -1 if difference > 0 else 1
            return (left.pre_rerank_rank or 0) - (right.pre_rerank_rank or 0)

        return sorted(updated, key=cmp_to_key(compare))

    @staticmethod
    def metadata(received: int, scored: int) -> dict:
        return {
            "mode": settings.reranking_mode,
            "model": safe_model_label(settings.reranking_model)
            if settings.reranking_mode == "cross_encoder"
            else None,
            "revision": settings.reranking_model_revision
            if settings.reranking_mode == "cross_encoder"
            else None,
            "candidates_received": received,
            "candidates_scored": scored,
        }


def _flatten_scores(raw: Any) -> list[float]:
    if hasattr(raw, "tolist"):
        raw = raw.tolist()
    if not isinstance(raw, (list, tuple)):
        raw = [raw]
    output: list[float] = []
    for value in raw:
        if isinstance(value, (list, tuple)):
            if len(value) != 1:
                raise RerankingScoreCountError(
                    "Reranker returned multiple values for one candidate."
                )
            value = value[0]
        output.append(float(value))
    return output


reranker = RerankerService()
