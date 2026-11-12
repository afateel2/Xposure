# Ported from ComplyX (backend/app/embeddings.py), see docs/PLAN.md section 1.
# Two changes since the port: sentence-transformers is imported lazily inside
# get_model() (it costs about 19 s to import and is not needed when every
# passage vector comes from the demo embedding cache), and embed_passages()
# consults that cache when demo mode activates it (see embedding_cache.py).

from functools import lru_cache
from typing import TYPE_CHECKING

from . import embedding_cache
from .config import settings

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

# multilingual-e5-large uses instruction prefixes:
# "query: " for search queries, "passage: " for documents
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "


@lru_cache(maxsize=1)
def get_model() -> "SentenceTransformer":
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.embedding_model)


def embed_query(text: str) -> list[float]:
    model = get_model()
    vector = model.encode(QUERY_PREFIX + text, normalize_embeddings=True)
    return vector.tolist()


def _embed_passages_uncached(texts: list[str]) -> list[list[float]]:
    model = get_model()
    prefixed = [PASSAGE_PREFIX + t for t in texts]
    vectors = model.encode(prefixed, normalize_embeddings=True, batch_size=32, show_progress_bar=True)
    return [v.tolist() for v in vectors]


def embed_passages(texts: list[str]) -> list[list[float]]:
    return embedding_cache.embed_with_cache(settings.embedding_model, texts, _embed_passages_uncached)
