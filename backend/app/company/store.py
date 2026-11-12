"""
The company workspace: the imaginary company's editable documents and the
versioned, sandboxed store the agent writes them through.

Two directories, one job each:

  backend/data/company_baseline/   pristine, committed, never written at runtime
  backend/data/company/            the runtime working copy (gitignored); created
                                   from the baseline on first use or on reset

Every write goes through `write_new_version()`, which keeps the whole
history as append-only files under `<company dir>/.history/`. A revert is
not a deletion: it writes the older content as a NEW version with origin
"revert", so "what did the agent do, and what was undone" can always be
reconstructed from the history alone.

Safety: every path that enters this module from outside (an API path, an
org node attribute) is resolved and verified to sit inside the company
directory before it is opened, only `.md` and `.yaml` files are allowed,
hidden path segments (including `.history`) are refused, and content is
size limited. The agent can therefore never be steered into writing outside
the sandbox by a crafted path.

Tests and experiments override the location with the COMPANY_DIR setting so
the real working copy is never dirtied.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ..config import settings

ALLOWED_EXTENSIONS = frozenset({".md", ".yaml"})
MAX_FILE_BYTES = 64 * 1024
HISTORY_DIRNAME = ".history"
PROFILE_NAME = "profile.yaml"

#: top-level folder -> document kind
KIND_BY_DIR = {
    "policies": "policy",
    "procedures": "procedure",
    "evidence": "evidence",
    "systems": "system",
}

ORIGINS = ("baseline", "agent", "revert")

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# One process-wide lock: the demo is a single-process app and every write is
# tiny, so a coarse lock is simpler and safer than per-file locking.
_LOCK = threading.RLock()

_VERSION_RE = re.compile(r"(?im)^[ \t]*(?:[-*][ \t]+)?(?:config_)?version:[ \t]*[\"']?([0-9][\w.\-]*)")
_REVIEWED_RE = re.compile(r"(?im)^[ \t]*(?:[-*][ \t]+)?last[ _]reviewed:[ \t]*[\"']?(\d{4}-\d{2}-\d{2})")


class CompanyStoreError(Exception):
    """Base class for every error this module raises on purpose."""


class UnsafePathError(CompanyStoreError, ValueError):
    """A path that is absolute, escapes the company directory, is hidden or has a disallowed extension."""


class FileNotInCompanyError(CompanyStoreError, LookupError):
    """A valid path that does not exist in the working copy."""


class InvalidContentError(CompanyStoreError, ValueError):
    """Content that is empty, too large, not valid UTF-8 or (for YAML) not a mapping."""


class NothingToRevertError(CompanyStoreError):
    """The file has no earlier version to restore."""


# Locations

def company_dir() -> Path:
    return Path(settings.company_dir).resolve() if settings.company_dir else (_DATA_DIR / "company").resolve()


def baseline_dir() -> Path:
    return Path(settings.company_baseline_dir).resolve() if settings.company_baseline_dir else (_DATA_DIR / "company_baseline").resolve()


def cache_dir() -> Path:
    return Path(settings.company_cache_dir).resolve() if settings.company_cache_dir else (_DATA_DIR / "company_cache").resolve()


# Path safety

def resolve_path(rel: str) -> tuple[str, Path]:
    """Normalize a client-supplied relative path and resolve it inside the
    company directory. Returns (posix relative path, absolute path).
    Raises UnsafePathError for anything that is not a plain, visible `.md`
    or `.yaml` file strictly inside the company directory."""
    if not isinstance(rel, str) or not rel.strip():
        raise UnsafePathError("Empty path.")
    if "\x00" in rel:
        raise UnsafePathError("Path contains a NUL byte.")
    norm = rel.replace("\\", "/").strip()
    if norm.startswith("/") or re.match(r"^[A-Za-z]:", norm):
        raise UnsafePathError(f"Absolute paths are not allowed: {rel!r}")
    if re.search(r'[:*?"<>|]', norm):
        raise UnsafePathError(f"Path contains a character that is not allowed: {rel!r}")
    parts = norm.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise UnsafePathError(f"Path must not contain empty, '.' or '..' segments: {rel!r}")
    if any(p.startswith(".") for p in parts):
        raise UnsafePathError(f"Hidden path segments are not allowed: {rel!r}")
    if parts[-1].endswith((" ", ".")):
        raise UnsafePathError(f"Invalid file name: {rel!r}")
    extension = os.path.splitext(parts[-1])[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise UnsafePathError(f"Only {sorted(ALLOWED_EXTENSIONS)} files are allowed, got {extension or 'no extension'!r}.")

    root = company_dir()
    target = (root / Path(*parts)).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise UnsafePathError(f"Path escapes the company directory: {rel!r}") from None
    return "/".join(parts), target


def kind_of(rel: str) -> str:
    return KIND_BY_DIR.get(rel.split("/", 1)[0], "other")


# Content helpers

def doc_version(content: str) -> str | None:
    """The `Version:` header value of a document (or `version:` key of a YAML file)."""
    match = _VERSION_RE.search(content)
    return match.group(1) if match else None


def doc_last_reviewed(content: str) -> str | None:
    match = _REVIEWED_RE.search(content)
    return match.group(1) if match else None


def bump_version(version: str | None) -> str:
    """1.0 -> 1.1, 1.9 -> 1.10, 2 -> 2.1, unparseable -> 1.1."""
    if not version:
        return "1.1"
    parts = version.split(".")
    if parts[-1].isdigit():
        if len(parts) == 1:
            return f"{parts[0]}.1"
        return ".".join([*parts[:-1], str(int(parts[-1]) + 1)])
    return f"{version}.1"


def validate_content(rel: str, content: str) -> str:
    """Normalize newlines and enforce the content rules. Returns the text to store."""
    if not isinstance(content, str) or not content.strip():
        raise InvalidContentError("Content is empty.")
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n"):
        text += "\n"
    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        raise InvalidContentError(f"Content exceeds the {MAX_FILE_BYTES // 1024} KiB limit.")
    if rel.lower().endswith(".yaml"):
        try:
            parsed = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise InvalidContentError(f"Content is not valid YAML: {exc}") from exc
        if not isinstance(parsed, dict):
            raise InvalidContentError("YAML content must be a mapping at the top level.")
    return text


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(text.encode("utf-8"))
    os.replace(tmp, path)


# Working copy lifecycle

def _managed_files(root: Path) -> list[str]:
    """Relative posix paths of every managed document under `root` (not the profile, not history)."""
    found: list[str] = []
    if not root.is_dir():
        return found
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        rel = path.relative_to(root).as_posix()
        if rel == PROFILE_NAME or any(part.startswith(".") for part in rel.split("/")):
            continue
        found.append(rel)
    return found


def _history_dir(rel: str) -> Path:
    return company_dir() / HISTORY_DIRNAME / Path(*rel.split("/"))


def _read_index(rel: str) -> list[dict[str, Any]]:
    index = _history_dir(rel) / "index.json"
    if not index.is_file():
        return []
    return json.loads(index.read_text(encoding="utf-8")).get("versions", [])


def _write_index(rel: str, versions: list[dict[str, Any]]) -> None:
    _atomic_write(_history_dir(rel) / "index.json", json.dumps({"path": rel, "versions": versions}, indent=2, ensure_ascii=False))


def _version_file(rel: str, n: int) -> Path:
    return _history_dir(rel) / f"v{n:04d}{os.path.splitext(rel)[1].lower()}"


def _seed_history(rel: str) -> list[dict[str, Any]]:
    """Version 1 = whatever is in the working copy right now, origin baseline."""
    versions = _read_index(rel)
    if versions:
        return versions
    _, target = resolve_path(rel)
    text = target.read_text(encoding="utf-8")
    entry = {
        "n": 1,
        "doc_version": doc_version(text),
        "origin": "baseline",
        "timestamp": _now(),
        "sha256": sha256_text(text),
        "size": len(text.encode("utf-8")),
        "action_id": None,
        "note": "Baseline copy",
    }
    _atomic_write(_version_file(rel, 1), text)
    _write_index(rel, [entry])
    return [entry]


def _copy_baseline(root: Path) -> None:
    base = baseline_dir()
    if not base.is_dir():
        raise CompanyStoreError(f"Baseline company directory not found: {base}")
    shutil.copytree(base, root, dirs_exist_ok=True, ignore=shutil.ignore_patterns(HISTORY_DIRNAME))
    for rel in _managed_files(root):
        _seed_history(rel)


def ensure_company() -> Path:
    """Create the working copy from the baseline if it does not exist yet. Idempotent."""
    root = company_dir()
    with _LOCK:
        if not (root / PROFILE_NAME).is_file():
            _copy_baseline(root)
        else:
            for rel in _managed_files(root):
                _seed_history(rel)
    return root


def _rmtree_writable(path: Path) -> None:
    def _onerror(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    shutil.rmtree(path, onerror=_onerror)


def reset_company() -> dict[str, Any]:
    """Restore the working copy from the baseline: the demo reset.

    Deletes the working copy AND its history and copies the pristine baseline
    in again, so the next run starts from version 1 everywhere. Refuses to
    delete a directory that is not recognizably a company working copy, so a
    mistyped COMPANY_DIR can never wipe an unrelated folder."""
    root = company_dir()
    base = baseline_dir()
    if not base.is_dir():
        raise CompanyStoreError(f"Baseline company directory not found: {base}")
    if root == base or base in root.parents or root in base.parents:
        raise CompanyStoreError("The working copy must be a separate directory from the baseline.")
    if len(root.parts) < 3:
        raise CompanyStoreError(f"Refusing to reset a top-level directory: {root}")
    with _LOCK:
        if root.exists():
            entries = [p for p in root.iterdir()]
            if entries and not (root / PROFILE_NAME).is_file():
                raise CompanyStoreError(f"Refusing to reset {root}: it does not look like a company working copy (no {PROFILE_NAME}).")
            _rmtree_writable(root)
        _copy_baseline(root)
    return {"dir": str(root), "files": len(_managed_files(root))}


# Reading

def load_profile() -> dict[str, Any]:
    root = ensure_company()
    return yaml.safe_load((root / PROFILE_NAME).read_text(encoding="utf-8")) or {}


def read_file(rel: str) -> str:
    ensure_company()
    rel, target = resolve_path(rel)
    if not target.is_file():
        raise FileNotInCompanyError(f"No such company file: {rel}")
    return target.read_text(encoding="utf-8")


def get_versions(rel: str) -> list[dict[str, Any]]:
    """Every version of a file, oldest first: {n, doc_version, origin, timestamp, sha256, size, action_id, note, ...}."""
    ensure_company()
    rel, target = resolve_path(rel)
    if not target.is_file():
        raise FileNotInCompanyError(f"No such company file: {rel}")
    with _LOCK:
        return [dict(v) for v in _seed_history(rel)]


def read_version(rel: str, n: int) -> str:
    versions = get_versions(rel)
    rel, _ = resolve_path(rel)
    if not any(v["n"] == n for v in versions):
        raise FileNotInCompanyError(f"{rel} has no version {n}")
    return _version_file(rel, n).read_text(encoding="utf-8")


def file_info(rel: str) -> dict[str, Any]:
    versions = get_versions(rel)
    rel, target = resolve_path(rel)
    latest = versions[-1]
    return {
        "path": rel,
        "name": target.name,
        "kind": kind_of(rel),
        "size": latest["size"],
        "version": latest["doc_version"],
        "last_modified": latest["timestamp"],
        "last_origin": latest["origin"],
        "version_count": len(versions),
        "agent_edited": latest["origin"] == "agent",
    }


def list_files() -> list[dict[str, Any]]:
    root = ensure_company()
    return [file_info(rel) for rel in _managed_files(root)]


# Writing

def write_new_version(
    rel: str,
    content: str,
    *,
    origin: str,
    action_id: int | None = None,
    note: str | None = None,
    reverted_to: int | None = None,
) -> dict[str, Any]:
    """Store `content` as the next version of an existing file and make it the working copy.

    Only existing managed files can be written: the agent edits documents, it
    does not create new files. Returns the new history entry."""
    if origin not in ORIGINS:
        raise ValueError(f"Unknown origin {origin!r}; expected one of {ORIGINS}")
    ensure_company()
    rel, target = resolve_path(rel)
    if not target.is_file():
        raise FileNotInCompanyError(f"No such company file: {rel}")
    text = validate_content(rel, content)
    with _LOCK:
        versions = _seed_history(rel)
        n = versions[-1]["n"] + 1
        entry: dict[str, Any] = {
            "n": n,
            "doc_version": doc_version(text),
            "origin": origin,
            "timestamp": _now(),
            "sha256": sha256_text(text),
            "size": len(text.encode("utf-8")),
            "action_id": action_id,
            "note": note,
        }
        if reverted_to is not None:
            entry["reverted_to"] = reverted_to
        _atomic_write(_version_file(rel, n), text)
        _atomic_write(target, text)
        _write_index(rel, [*versions, entry])
        return dict(entry)


def revert_to_version(rel: str, n: int, *, action_id: int | None = None, note: str | None = None) -> dict[str, Any]:
    """Restore version `n`'s content as a NEW version (history is append-only)."""
    text = read_version(rel, n)
    return write_new_version(rel, text, origin="revert", action_id=action_id, note=note or f"Restored version {n}", reverted_to=n)


def revert_to_previous(rel: str, *, action_id: int | None = None) -> dict[str, Any]:
    """Restore the version before the latest one as a new version."""
    versions = get_versions(rel)
    if len(versions) < 2:
        raise NothingToRevertError(f"{rel} has no earlier version to restore.")
    return revert_to_version(rel, versions[-2]["n"], action_id=action_id, note=f"Restored version {versions[-2]['n']}")
