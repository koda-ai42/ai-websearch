from __future__ import annotations

import asyncio
import logging
from typing import Any

import numpy as np

from .config import settings
from .logging_utils import log_extra
from .security import safe_model_label
from .store import embedding_metadata, ensure_embedding_metadata

logger = logging.getLogger(__name__)


def _model_dimension(model: Any) -> int | None:
    getter = getattr(model, "get_embedding_dimension", None)
    if not callable(getter):
        getter = getattr(model, "get_sentence_embedding_dimension", None)
    dimension = getter() if callable(getter) else None
    return int(dimension) if dimension else None


class Embedder:
    """Lazy, in-process sentence-transformers embedder."""

    def __init__(self) -> None:
        self.model_name = settings.embedding_model
        self.model_revision = settings.embedding_model_revision
        self.model_identity = settings.embedding_model_identity
        self._model: Any | None = None
        self._dimension: int | None = None
        self._load_lock = asyncio.Lock()

    async def _load(self) -> Any:
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is None:
                from sentence_transformers import SentenceTransformer

                device = None if settings.embedding_device == "auto" else settings.embedding_device
                model = await asyncio.to_thread(
                    SentenceTransformer,
                    self.model_name,
                    device=device,
                    cache_folder=settings.embedding_cache_path,
                    revision=self.model_revision,
                )
                self._model = model
                dim = _model_dimension(model)
                if dim:
                    self._dimension = dim
                    ensure_embedding_metadata(self.model_identity, self._dimension)
        return self._model

    async def embed_texts(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        try:
            model = await self._load()
            vectors = await asyncio.to_thread(
                model.encode,
                texts,
                batch_size=settings.embedding_batch_size,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            array = np.asarray(vectors, dtype=np.float32)
            if array.ndim != 2:
                raise ValueError(
                    f"Embedding model returned shape {array.shape}; expected a 2-D array"
                )
            self._dimension = int(array.shape[1])
            ensure_embedding_metadata(self.model_identity, self._dimension)
            return array
        except Exception as exc:
            log_extra(
                logger,
                logging.ERROR,
                "embedding_failed",
                model=safe_model_label(self.model_name),
                error=type(exc).__name__,
            )
            raise RuntimeError("Embedding inference failed without exposing local paths.") from exc

    async def embed_query(self, query: str) -> np.ndarray:
        vectors = await self.embed_texts([query])
        return vectors[0]

    def metadata(self) -> dict:
        stored = embedding_metadata()
        return {
            "backend": "sentence_transformers",
            "model": safe_model_label(self.model_name),
            "revision": self.model_revision,
            "dimension": self._dimension or stored.get("embedding_dimension"),
            "normalized": True,
        }


embedder = Embedder()
