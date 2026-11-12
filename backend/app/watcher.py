"""
A REAL live check against a regulator's own public page, not the
simulated local-mirror portal app/demo/ uses for the guided demo pipeline
(see that package's module docstrings). This is the live crawler in its
first honest, narrow form: on-demand, one
regulation at a time, never scheduled or looped by this code (no in-app
scheduler exists anywhere in this project, see app/digest.py's own
docstring for the same point).

Verified directly against the real page (not assumed from a template),
the same discipline ECC-1:2018's own sourcing used (docs/PLAN.md section
1): https://nca.gov.sa/en/regulatory-documents/controls-list/ecc is a
real, plain-HTTP-fetchable (no JS execution required, confirmed with a
raw GET, not just a rendered browser) page that embeds the current ECC
version label ("ECC 2-2024") and a direct PDF link under
cdn.nca.gov.sa/api/files/public/upload/. NCA also publishes a companion
"Guide to Essential Cybersecurity Controls (ECC) Implementation" PDF from
the same page; it is excluded by name (see _MAIN_DOC_EXCLUDE) so the
watcher never mistakes the implementation guide for a new edition of the
regulation itself.

What this does NOT do, stated rather than hidden:
  - It never ingests anything automatically. A detected new version is
    reported; a human runs `python -m app.ingest` to actually bring it
    in, exactly like a file dropped in data/sources/ today. Auto-ingesting
    unreviewed regulatory text would be a materially different, much
    larger trust claim than this project makes anywhere else (every
    other agent action is draft-then-approve or narrower, see
    app/policy.py).
  - It is not scheduled. Nothing in this codebase calls check_live() on a
    timer; it runs when a person (or a future, separately-decided
    scheduler) explicitly asks it to, via POST /sources/check-live.
  - It only knows about NCA/ECC today. SASO's RoHS regulation (see
    app/ingest_articles.py) was onboarded by directly sourcing and
    ingesting its current PDF; its live listing page was not
    investigated for this watcher, and is not assumed to have the same
    shape as NCA's without checking it first (docs/DESIGN.md's own Risks
    section makes exactly this point about a second regulator's PDF
    table conventions, and the same caution applies to a listing page's
    HTML structure).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db.models import Regulation, RegulationVersion, Regulator

USER_AGENT = "XposureComplianceMonitor/1.0 (+regulatory change monitoring; one-off checks, not scheduled)"
_REQUEST_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0)


@dataclass(frozen=True)
class WatchTarget:
    regulator_code: str
    regulation_code: str
    page_url: str
    # Matches the version label as NCA's own page renders it, e.g. "ECC 2-2024".
    version_re: re.Pattern
    # Any PDF link under this prefix is a candidate for the main document.
    pdf_link_re: re.Pattern
    # Filenames containing any of these (case-insensitive) are companion
    # material (an implementation guide), never the regulation itself.
    exclude_name_substrings: tuple[str, ...]


NCA_ECC_TARGET = WatchTarget(
    regulator_code="nca",
    regulation_code="ecc",
    page_url="https://nca.gov.sa/en/regulatory-documents/controls-list/ecc",
    # Group 1 is already this project's own version_label shape ("2-2024"),
    # matching every RegulationVersion row ingest.py has ever written for
    # this regulation, no separate normalization step needed.
    version_re=re.compile(r"ECC\s+(\d+-\d{4})"),
    pdf_link_re=re.compile(r"https://cdn\.nca\.gov\.sa/api/files/public/upload/[^\"'\\\s]+?\.pdf"),
    exclude_name_substrings=("guide", "implementation"),
)

WATCH_TARGETS: dict[tuple[str, str], WatchTarget] = {
    (NCA_ECC_TARGET.regulator_code, NCA_ECC_TARGET.regulation_code): NCA_ECC_TARGET,
}


class WatcherError(Exception):
    """kind: timeout | unreachable | bad_status | unrecognized_page | pdf_unreachable.
    Mirrors app/erp/client.py's ErpError shape (message_en/message_ar/combined)
    so routes can surface it the same way."""

    def __init__(self, kind: str, message_en: str, message_ar: str):
        super().__init__(message_en)
        self.kind = kind
        self.message_en = message_en
        self.message_ar = message_ar

    @property
    def combined(self) -> str:
        return f"{self.message_en} | {self.message_ar}"


def _fetch(url: str) -> httpx.Response:
    try:
        with httpx.Client(timeout=_REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
            return client.get(url)
    except httpx.TimeoutException as exc:
        raise WatcherError(
            "timeout",
            f"The regulator's site did not answer in time ({url}).",
            "لم تستجب بوابة الجهة التنظيمية في الوقت المحدد.",
        ) from exc
    except httpx.HTTPError as exc:
        raise WatcherError(
            "unreachable",
            f"Could not reach the regulator's site: {type(exc).__name__}.",
            "تعذر الوصول إلى موقع الجهة التنظيمية.",
        ) from exc


def check_live(db: Session, target: WatchTarget) -> dict[str, Any]:
    """One real, synchronous check. Takes a few seconds (one page fetch,
    one PDF download to hash it). Never caches internally; routes/sources.py
    owns the short-lived cache so repeated UI loads don't repeat the real
    network calls (see that module)."""
    checked_at = datetime.now(timezone.utc)
    page_resp = _fetch(target.page_url)
    if page_resp.status_code != 200:
        raise WatcherError(
            "bad_status",
            f"The regulator's page returned HTTP {page_resp.status_code}.",
            f"أعادت صفحة الجهة التنظيمية الحالة {page_resp.status_code}.",
        )
    html = page_resp.text

    version_match = target.version_re.search(html)
    pdf_candidates = target.pdf_link_re.findall(html)
    main_pdf_url = next(
        (u for u in pdf_candidates if not any(s in u.lower() for s in target.exclude_name_substrings)),
        None,
    )

    if version_match is None or main_pdf_url is None:
        raise WatcherError(
            "unrecognized_page",
            "The page loaded, but its known version/link pattern was not found. "
            "The site's layout may have changed; this watcher needs updating, not trusting blindly.",
            "تم تحميل الصفحة، لكن تعذر العثور على نمط الإصدار أو الرابط المعروف. "
            "قد يكون شكل الصفحة قد تغيّر.",
        )

    live_version_label = version_match.group(1)

    known_versions = {
        row.version_label: row.file_sha256
        for row in db.scalars(
            select(RegulationVersion)
            .join(Regulation, RegulationVersion.regulation_id == Regulation.id)
            .join(Regulator, Regulation.regulator_id == Regulator.id)
            .where(Regulator.code == target.regulator_code, Regulation.code == target.regulation_code)
        )
    }

    result: dict[str, Any] = {
        "regulator": target.regulator_code,
        "regulation": target.regulation_code,
        "checked_at": checked_at.isoformat(),
        "page_url": target.page_url,
        "live_version_label": live_version_label,
        "pdf_url": main_pdf_url,
        "known_versions": sorted(known_versions),
    }

    if live_version_label not in known_versions:
        result["status"] = "new_version_available"
        result["message_en"] = (
            f"{target.regulation_code.upper()} {live_version_label} is published on the regulator's site "
            f"and is not yet ingested. Run the ingest command to bring it in."
        )
        result["message_ar"] = (
            f"نسخة {live_version_label} منشورة على موقع الجهة التنظيمية وغير مستوعبة بعد في النظام."
        )
        result["file_sha256"] = None
        return result

    # Known version label: download the real PDF to confirm the CONTENT
    # still matches what was ingested (the same republish-under-the-same-
    # label case app/agent/graph.py's detect_new_sources() already names
    # as "conflict" for the file-drop path).
    pdf_resp = _fetch(main_pdf_url)
    if pdf_resp.status_code != 200:
        raise WatcherError(
            "pdf_unreachable",
            f"Found the {live_version_label} link but could not download it (HTTP {pdf_resp.status_code}).",
            f"تعذر تنزيل نسخة {live_version_label} للتحقق منها.",
        )
    live_sha256 = hashlib.sha256(pdf_resp.content).hexdigest()
    known_sha256 = known_versions[live_version_label]
    result["file_sha256"] = live_sha256

    if live_sha256 == known_sha256:
        result["status"] = "matches_known"
        result["message_en"] = f"{live_version_label} on the regulator's site matches what is already ingested."
        result["message_ar"] = f"نسخة {live_version_label} على موقع الجهة التنظيمية مطابقة لما تم استيعابه."
    else:
        result["status"] = "content_conflict"
        result["message_en"] = (
            f"{live_version_label} is live on the regulator's site but its content no longer matches the "
            f"ingested copy (different SHA-256). The regulator may have republished this edition."
        )
        result["message_ar"] = (
            f"نسخة {live_version_label} منشورة حالياً لكن محتواها يختلف عن النسخة المستوعبة سابقاً."
        )
    return result
