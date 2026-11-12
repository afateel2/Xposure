"""
On-disk cache of passage embeddings, keyed by a hash of the model name and
the exact text (demo mode only, same activation as app/llm_cache.py).

Measured on this machine (CPU only): embedding the 233 clauses of ECC-2:2024
with multilingual-e5-large takes about 50 s, plus about 28 s to load the
model and about 19 s to import sentence-transformers. That is most of the
"ingest" stage of a replayed demo. A cached vector is byte-for-byte the
vector the model produced for the identical text earlier, so replays skip
the model entirely (it is not even loaded when every text is cached).

The demo run reports how many vectors were read from this cache, so a
replayed ingest is never presented as a fresh embedding run.

Files live under backend/data/cache/embeddings/ (already gitignored via
backend/data/cache/), one float32 `.npy` per text. A corrupt or unreadable
file is treated as a miss and recomputed.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np

from . import llm_cache

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "embeddings"

_lock = threading.Lock()
_stats = {"texts": 0, "cache_hits": 0}


def stats_snapshot() -> dict[str, int]:
    with _lock:
        return dict(_stats)


def _key(model: str, text: str) -> str:
    return hashlib.sha256(f"passage:{model}\x00{text}".encode("utf-8")).hexdigest()


def _path(model: str, text: str) -> Path:
    return CACHE_DIR / f"{_key(model, text)}.npy"


def _load(model: str, text: str) -> list[float] | None:
    path = _path(model, text)
    try:
        if path.is_file():
            return np.load(path, allow_pickle=False).tolist()
    except Exception:
        return None
    return None


def _store(model: str, text: str, vector: list[float]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _path(model, text)
        tmp = path.with_name(path.name + ".tmp.npy")
        np.save(tmp, np.asarray(vector, dtype=np.float32), allow_pickle=False)
        tmp.replace(path)
    except Exception:
        pass  # a failed cache write costs speed on the next replay, nothing else


def embed_with_cache(
    model: str, texts: list[str], embed_uncached: Callable[[list[str]], list[list[float]]]
) -> list[list[float]]:
    """Vectors for `texts` in order. Reads the disk cache when the demo
    cache is active; embeds only the texts that are missing."""
    if not llm_cache.is_active():
        return embed_uncached(texts)

    vectors: list[list[float] | None] = [_load(model, t) for t in texts]
    missing = [i for i, v in enumerate(vectors) if v is None]
    with _lock:
        _stats["texts"] += len(texts)
        _stats["cache_hits"] += len(texts) - len(missing)
    if missing:
        fresh = embed_uncached([texts[i] for i in missing])
        for i, vector in zip(missing, fresh):
            vectors[i] = vector
            _store(model, texts[i], vector)
    return [v for v in vectors if v is not None]
