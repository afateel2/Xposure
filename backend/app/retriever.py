"""
Qdrant access: collection lifecycle + semantic search. Ported from
ComplyX's retriever.py (docs/PLAN.md section 1) — same balancing/
exact-search pattern, with corpus filtering replaced by
regulator/regulation/version filtering (Xposure has one flat corpus per
regulation rather than ComplyX's many parallel corpora).
"""

from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, SearchParams, VectorParams

from .config import settings

VECTOR_SIZE = 1024  # multilingual-e5-large output dimension


@lru_cache(maxsize=1)
def get_client() -> QdrantClient:
    return QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)


def ensure_collection_exists() -> None:
    client = get_client()
    existing = {c.name for c in client.get_collections().collections}
    if settings.qdrant_collection not in existing:
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )


def _hit_to_dict(hit) -> dict:
    return {
        "score": hit.score,
        "regulator": hit.payload.get("regulator", ""),
        "regulation": hit.payload.get("regulation", ""),
        "version": hit.payload.get("version", ""),
        "clause_id": hit.payload.get("clause_id", ""),
        "parent_clause_id": hit.payload.get("parent_clause_id"),
        "lang": hit.payload.get("lang", ""),
        "text": hit.payload.get("text", ""),
        "page": hit.payload.get("page"),
    }


def search(
    query: str,
    limit: int = 8,
    regulator: str | None = None,
    regulation: str | None = None,
    version: str | None = None,
) -> list[dict]:
    """Semantic search, optionally scoped to a regulator/regulation/version.
    Embeds `query` itself — pass a query STRING, not a precomputed vector
    (use search_by_vector for the M3 embedding-similarity fallback match,
    which already has a clause's vector on hand and shouldn't re-embed it)."""
    from .embeddings import embed_query

    return search_by_vector(embed_query(query), limit, regulator, regulation, version)


def search_by_vector(
    vector: list[float],
    limit: int = 8,
    regulator: str | None = None,
    regulation: str | None = None,
    version: str | None = None,
) -> list[dict]:
    conditions = []
    if regulator:
        conditions.append(FieldCondition(key="regulator", match=MatchValue(value=regulator)))
    if regulation:
        conditions.append(FieldCondition(key="regulation", match=MatchValue(value=regulation)))
    if version:
        conditions.append(FieldCondition(key="version", match=MatchValue(value=version)))
    flt = Filter(must=conditions) if conditions else None

    response = get_client().query_points(
        collection_name=settings.qdrant_collection,
        query=vector,
        query_filter=flt,
        limit=limit,
        with_payload=True,
        with_vectors=False,
        # Exact (brute-force) search: at Xposure's corpus scale (one
        # regulation's controls, low thousands of points at most) the
        # latency cost is negligible, and it avoids HNSW's approximate
        # search returning a different order across identical calls with
        # the identical query vector (same reasoning as ComplyX's retriever.py).
        search_params=SearchParams(exact=True),
    )
    return [_hit_to_dict(h) for h in response.points]


def get_vectors_for_version(regulator: str, regulation: str, version: str) -> dict[str, list[float]]:
    """clause_id -> embedding vector for every clause of one regulation
    version, for diff.py's embedding-similarity alignment fallback (M3) —
    reuses the vectors computed at ingestion time instead of re-embedding."""
    flt = Filter(must=[
        FieldCondition(key="regulator", match=MatchValue(value=regulator)),
        FieldCondition(key="regulation", match=MatchValue(value=regulation)),
        FieldCondition(key="version", match=MatchValue(value=version)),
    ])
    client = get_client()
    out: dict[str, list[float]] = {}
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=settings.qdrant_collection,
            scroll_filter=flt,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        for p in points:
            out[p.payload["clause_id"]] = p.vector
        if offset is None:
            break
    return out


def count_indexed(regulator: str | None = None, regulation: str | None = None, version: str | None = None) -> int:
    conditions = []
    if regulator:
        conditions.append(FieldCondition(key="regulator", match=MatchValue(value=regulator)))
    if regulation:
        conditions.append(FieldCondition(key="regulation", match=MatchValue(value=regulation)))
    if version:
        conditions.append(FieldCondition(key="version", match=MatchValue(value=version)))
    flt = Filter(must=conditions) if conditions else None
    try:
        return get_client().count(collection_name=settings.qdrant_collection, count_filter=flt, exact=True).count
    except Exception:
        return 0
