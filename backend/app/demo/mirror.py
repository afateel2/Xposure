"""
The regulator portal, simulated by a local folder for the guided demo.

`backend/data/portal_mirror/<regulator>/` holds every document the "portal"
publishes, under the same file names the agent recognises (see
agent/graph.py KNOWN_SOURCES). `backend/data/sources/` is what the company
has already downloaded. A scan lists the mirror, compares it with the
versions the database already knows, and "fetches" a new document by
copying it from the mirror into the sources folder, after which the real
graph takes over (check_sources notices the file, ingest_new ingests it).

This is a stand-in and is labelled as one everywhere the user can see it.
The live check against the real NCA page is separate (app/watcher.py, the
Sources screen's "Check now"). Copying a local file is not presented as a
network download.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from ..agent import graph

MIRROR_DIR = Path(__file__).resolve().parents[2] / "data" / "portal_mirror"

_sha_cache: dict[tuple[str, int, int], str] = {}
_sha_lock = threading.Lock()


@dataclass
class PortalDocument:
    path: str  # posix path relative to the mirror root, e.g. "nca/Essential ... (ECC-2-2024).pdf"
    filename: str
    sha256: str
    size_bytes: int
    regulator: str | None
    regulation: str | None
    version_label: str | None
    #: known: this exact file is ingested. new: recognised and not ingested.
    #: conflict: its version label is ingested with different bytes.
    #: unrecognized: file name is not in KNOWN_SOURCES.
    status: str

    def as_dict(self) -> dict:
        return asdict(self)


def file_sha256(path: Path) -> str:
    stat = path.stat()
    cache_key = (str(path), stat.st_size, stat.st_mtime_ns)
    with _sha_lock:
        cached = _sha_cache.get(cache_key)
    if cached:
        return cached
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    value = digest.hexdigest()
    with _sha_lock:
        _sha_cache[cache_key] = value
    return value


def _files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*") if p.is_file() and not p.name.startswith("."))


def seed_mirror() -> list[str]:
    """Make sure the mirror holds a copy of every recognised source the
    company already has, so that removing a document from the sources folder
    (reset) can never lose the only copy. Existing mirror files are never
    overwritten. Returns the relative paths copied."""
    sources = graph.SOURCES_DIR
    copied: list[str] = []
    for src in _files(sources):
        if src.name not in graph.KNOWN_SOURCES:
            continue
        rel = src.relative_to(sources)
        dest = MIRROR_DIR / rel
        if dest.is_file():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(rel.as_posix())
    return copied


def list_portal(db: Session) -> list[PortalDocument]:
    """Every document the portal mirror publishes, with its status against
    the versions the database already knows."""
    docs: list[PortalDocument] = []
    for path in _files(MIRROR_DIR):
        digest = file_sha256(path)
        rel = path.relative_to(MIRROR_DIR).as_posix()
        known = graph.KNOWN_SOURCES.get(path.name)
        if known is None:
            docs.append(PortalDocument(rel, path.name, digest, path.stat().st_size, None, None, None, "unrecognized"))
            continue
        existing = graph._find_version(db, known.regulator_code, known.regulation_code, known.version_label)
        if existing is None:
            status = "new"
        elif existing.file_sha256 == digest:
            status = "known"
        else:
            status = "conflict"
        docs.append(
            PortalDocument(
                rel, path.name, digest, path.stat().st_size,
                known.regulator_code, known.regulation_code, known.version_label, status,
            )
        )
    return docs


def fetch(doc: PortalDocument) -> dict:
    """Copy one document from the mirror into the sources folder and verify
    the copy byte for byte (SHA-256). Returns what was fetched."""
    src = MIRROR_DIR / doc.path
    dest = graph.SOURCES_DIR / doc.path
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    shutil.copy2(src, tmp)
    if file_sha256(tmp) != doc.sha256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Copy of {doc.filename} from the portal mirror did not match its checksum.")
    os.replace(tmp, dest)
    return {"path": doc.path, "filename": doc.filename, "sha256": doc.sha256, "size_bytes": doc.size_bytes}


def remove_non_baseline_sources(baseline_label: str) -> list[str]:
    """Reset helper: delete recognised sources whose version is not the
    baseline from the sources folder, but only after the mirror is
    guaranteed to hold an identical copy. Returns relative paths removed."""
    seed_mirror()
    removed: list[str] = []
    sources = graph.SOURCES_DIR
    for src in _files(sources):
        known = graph.KNOWN_SOURCES.get(src.name)
        if known is None or known.version_label == baseline_label:
            continue
        mirror_copy = MIRROR_DIR / src.relative_to(sources)
        if not mirror_copy.is_file() or file_sha256(mirror_copy) != file_sha256(src):
            raise RuntimeError(
                f"Refusing to remove {src.name} from the sources folder: the portal mirror has no "
                f"identical copy of it."
            )
        src.unlink()
        removed.append(src.relative_to(sources).as_posix())
    return removed
