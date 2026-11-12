"""
Citation check: is the clause text we show actually in the source file?

The diff receipt shows old and new clause text from the database and cites a
page and a file hash. This module closes the loop with plain code, no model:
it opens the stored source PDF, confirms the file still has the hash recorded
at ingestion, and looks for the clause text on the cited page.

What "verbatim" means here, stated so the badge is never read as more than it
is: text is compared with case, whitespace and punctuation ignored (a PDF
wraps lines and mixes dash and quote styles), but every word must be present
in order. A clause whose text was stitched together from two places in the
document (for example a change-list table that lists previous and updated
wording in separate cells) is reported as not found. That is the point of the
check: it flags text a reviewer should read in the original.

Statuses:
  verified      found on the cited page
  other_page    found, but on a different page than the one cited
  not_found     not found anywhere in the file
  file_changed  the file on disk no longer matches the hash recorded at ingestion
  unavailable   no source file for this version, or it could not be read
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# Short strings (titles such as "Cybersecurity policies") occur all over a
# document, so a match on some other page proves nothing. Below this many
# normalized characters the whole-document search is skipped.
MIN_ELSEWHERE_CHARS = 60


@dataclass(frozen=True)
class CitationCheck:
    status: str
    page: int | None = None  # 1-based page where the text was found
    cited_page: int | None = None  # the page the change cites
    file_hash_ok: bool | None = None  # None when the file could not be hashed
    reason: str | None = None  # why the check was unavailable


def normalize(text: str | None) -> str:
    """Lower-case letters and digits only: ignores whitespace, punctuation and
    dash/quote variants, keeps word order."""
    return "".join(re.findall(r"\w+", (text or "").lower()))


@lru_cache(maxsize=8)
def _load_pdf(path_str: str, mtime_ns: int, size: int) -> tuple[tuple[str, ...], str]:
    """(normalized text per page, sha256 of the file). The key includes mtime
    and size so a replaced file is re-read, never served from a stale cache."""
    import fitz  # PyMuPDF, imported lazily: only the detail endpoint needs it

    data = Path(path_str).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        pages = tuple(normalize(page.get_text("text")) for page in doc)
    finally:
        doc.close()
    return pages, sha


def check_clause_text(
    pdf_path: Path | None,
    expected_sha256: str | None,
    clause_text: str | None,
    cited_page: int | None,
) -> CitationCheck:
    """Look for `clause_text` in `pdf_path`, starting at `cited_page`."""
    if pdf_path is None or not Path(pdf_path).is_file():
        return CitationCheck(status="unavailable", cited_page=cited_page, reason="source file not found")
    needle = normalize(clause_text)
    if not needle:
        return CitationCheck(status="unavailable", cited_page=cited_page, reason="no clause text to check")
    try:
        stat = Path(pdf_path).stat()
        pages, sha = _load_pdf(str(pdf_path), stat.st_mtime_ns, stat.st_size)
    except Exception as exc:  # unreadable or corrupt file: report, never fail the request
        return CitationCheck(status="unavailable", cited_page=cited_page, reason=f"could not read file ({type(exc).__name__})")

    hash_ok = (sha == expected_sha256) if expected_sha256 else None
    if hash_ok is False:
        return CitationCheck(status="file_changed", cited_page=cited_page, file_hash_ok=False)

    if cited_page is not None and 1 <= cited_page <= len(pages) and needle in pages[cited_page - 1]:
        return CitationCheck(status="verified", page=cited_page, cited_page=cited_page, file_hash_ok=hash_ok)
    if len(needle) >= MIN_ELSEWHERE_CHARS:
        for index, page_text in enumerate(pages):
            if needle in page_text:
                return CitationCheck(status="other_page", page=index + 1, cited_page=cited_page, file_hash_ok=hash_ok)
    return CitationCheck(status="not_found", cited_page=cited_page, file_hash_ok=hash_ok)


def source_pdf_path(regulator_code: str, regulation_code: str, version_label: str) -> Path | None:
    """The stored source file for an ingested version, or None when this
    version's file name is not registered (a manually ingested document)."""
    from .agent import graph  # lazy: pulls in the whole agent graph

    for known in graph.KNOWN_SOURCES.values():
        if (known.regulator_code, known.regulation_code, known.version_label) == (
            regulator_code,
            regulation_code,
            version_label,
        ):
            candidate = graph.SOURCES_DIR / known.regulator_code / known.filename
            if candidate.is_file():
                return candidate
            try:
                from .demo import mirror  # the portal mirror keeps a copy of every recognised file

                fallback = mirror.MIRROR_DIR / known.regulator_code / known.filename
                return fallback if fallback.is_file() else None
            except Exception:
                return None
    return None
