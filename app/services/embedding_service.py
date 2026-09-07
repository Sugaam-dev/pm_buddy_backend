import hashlib
import logging
import math
from abc import ABC, abstractmethod
import os
from typing import Optional
import google.generativeai as genai

from app.core.config import settings

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSION = 768


def generate_deterministic_embedding(text: str, dim: int = EMBEDDING_DIMENSION) -> list[float]:
    """Generates a deterministic, unit-normalized fallback embedding based on SHA-256 hash.
    Used when Gemini API key is missing, network is unavailable, or quota is exhausted.
    """
    if not text.strip():
        return [0.0] * dim

    # Use multi-seed hashing to produce pseudo-random unit vector
    vec = []
    text_bytes = text.encode("utf-8")
    for i in range(dim):
        seed = f"{i}:{text}".encode("utf-8")
        h = int(hashlib.sha256(seed).hexdigest()[:8], 16)
        val = (h / 0xFFFFFFFF) * 2.0 - 1.0
        vec.append(val)

    # Normalize to unit length
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


class IEmbeddingService(ABC):
    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Generate embedding vector for a single text."""
        pass

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embedding vectors for a list of texts."""
        pass


class GeminiEmbeddingService(IEmbeddingService):
    def __init__(self, api_key: Optional[str] = None, model: str = "models/gemini-embedding-001"):
        self.api_key = api_key or settings.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY")
        self.model = model
        if self.api_key:
            try:
                genai.configure(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Could not configure genai with key: {e}")

    async def embed(self, text: str) -> list[float]:
        if not text or not text.strip():
            return [0.0] * EMBEDDING_DIMENSION

        if getattr(settings, "ENVIRONMENT", "").lower() == "test":
            return generate_deterministic_embedding(text, EMBEDDING_DIMENSION)

        try:
            res = genai.embed_content(
                model=self.model,
                content=text,
                task_type="retrieval_document",
            )
            embedding = res.get("embedding", [])
            if len(embedding) == EMBEDDING_DIMENSION:
                return embedding
            elif len(embedding) > 0:
                # Pad or truncate if needed
                if len(embedding) > EMBEDDING_DIMENSION:
                    return embedding[:EMBEDDING_DIMENSION]
                return embedding + [0.0] * (EMBEDDING_DIMENSION - len(embedding))
        except Exception as e:
            logger.warning(f"Gemini embed_content call failed: {e}. Using deterministic fallback.")

        return generate_deterministic_embedding(text, EMBEDDING_DIMENSION)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        results = []
        for text in texts:
            vec = await self.embed(text)
            results.append(vec)
        return results


# Global singleton instance
embedding_service = GeminiEmbeddingService()
