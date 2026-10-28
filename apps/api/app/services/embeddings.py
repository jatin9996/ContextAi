import asyncio
import hashlib
import logging

from app.core.config import settings
from app.core.constants import EMBEDDING_DIM
from app.core.errors import ProcessingError
from app.services.textutil import l2_normalize, tokenize

logger = logging.getLogger(__name__)


def hash_embed(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    tokens = tokenize(text) or {"empty"}
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "little") % EMBEDDING_DIM
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vector[index] += sign
    return l2_normalize(vector)


class EmbeddingService:
    """Local fastembed by default, with an explicit hashing fallback.

    The hashing provider is deterministic and useful for tests. It is not a semantic model.
    Health and diagnostics report which provider actually ran.
    """

    def __init__(self) -> None:
        self.provider = settings.embedding_provider
        self.warning: str | None = None
        self._model = None

    def _load_fastembed(self):
        if self._model is not None:
            return self._model
        try:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=settings.embedding_model)
            return self._model
        except Exception as exc:
            self.provider = "hashing"
            self.warning = "fastembed_unavailable"
            logger.warning(
                "Fastembed is unavailable; using hashing embeddings",
                extra={"component": "embeddings", "error_category": type(exc).__name__},
            )
            return None

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        if self.provider == "fastembed":
            model = self._load_fastembed()
            if model is not None:
                vectors = [l2_normalize([float(value) for value in vector]) for vector in model.embed(texts)]
                self._check(vectors)
                return vectors
        vectors = [hash_embed(text) for text in texts]
        self._check(vectors)
        return vectors

    def _check(self, vectors: list[list[float]]) -> None:
        for vector in vectors:
            if len(vector) != EMBEDDING_DIM:
                raise ProcessingError(
                    "embedding_dimensions",
                    "The embedding provider returned an unexpected vector size.",
                )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(self._embed_sync, texts)

    def status(self) -> dict[str, str | None]:
        return {"provider": self.provider, "warning": self.warning}


_service: EmbeddingService | None = None


def get_embeddings() -> EmbeddingService:
    global _service
    if _service is None:
        _service = EmbeddingService()
    return _service
