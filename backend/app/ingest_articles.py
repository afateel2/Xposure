"""
Ingestion for Article-numbered regulations (SASO's "Article (N) Title" /
numbered "N/M" provisions, Annex-based appendices) — a different document
shape from NCA ECC's two-column code|text table (app/ingest.py), confirmed
by rendering the real PDF, not assumed from the fact that both are
regulatory PDFs. ingest.py's own module docstring says a third regulator
that doesn't fit either ECC convention should get its own explicit case
rather than a guesser; this module is that case, built generic enough
(an ArticleSpec per regulation) that a future Article-numbered regulation
doesn't need to start over, but validated against exactly one real
document (SASO's RoHS technical regulation) so far, not assumed to
generalize further than that until a second one is actually tried.

Run as:
  python -m app.ingest_articles --regulator saso --regulation rohs \
      --version 2-2022 --spec saso_rohs \
      --file "data/sources/saso/TR-RoHS-V2-EN.pdf"

Source, verified directly against saso.gov.sa (not a third-party mirror,
the same discipline ECC-1:2018's sourcing used, docs/PLAN.md section 1):
  https://saso.gov.sa/en/Laws-And-Regulations/Technical_regulations/Documents/TR-Restriction-of-hazardous-Substance-in-Electrical-and-Electronic-Equipment-V2.pdf
  Cover page: "Version (2)", approved by SASO's Board of Directors No. 186
  on 30/06/2022, published in the Official Gazette 29/07/2022.

English only for now. A genuine, verifiably-official Version (1) PDF
(approved 9 July 2021 per third-party trade-compliance sources) could not
be found hosted at saso.gov.sa itself; SASO's site only currently serves
the superseded version under a distinct URL when the update is explicit
(the "-V2" suffix), and no unversioned or "-V1" English file resolves
there today. Shipping an unverified copy from a vendor mirror would break
this project's own "verified, not assumed" sourcing rule (see ECC-1:2018's
sourcing note in docs/PLAN.md section 1), so only the current version is
ingested; a real version-diff for this regulation waits for an actual new
edition to be verifiably published, exactly like NCA ECC waited for a
second edition to exist before diff.py had anything to compare. An Arabic
PDF of the same edition is real and was located (saso.gov.sa, "/ar/" path)
but its parsing is not attempted here — text_ar stays empty, honestly, the
same state NCA ECC's clauses are already in (see docs/DESIGN.md's Risks:
"text_ar is empty for every ingested clause today").

Two known, accepted coverage limits, stated rather than hidden:
  - Numbered "N/M" provisions inside Articles 1-11 are captured at full
    granularity (this is where the real supplier obligations and
    procedures live, which is what diff/impact care about).
  - Annexes (1 through 4) are each captured as ONE clause holding their
    full verbatim text. Annex 1-a/1-b/2-a/2-b are themselves numbered
    lists/tables (substance exemptions, standard references, customs
    codes); splitting those into individually-addressable rows is real,
    additional parsing work (a different shape again, not attempted in
    this pass) rather than guessed at. Nothing is dropped or summarized,
    the raw extracted text is kept in full; it is simply one coarser
    clause per annex instead of one row per table line.
"""

import argparse
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db.models import Clause, RegulationVersion
from .db.session import get_engine
from .embeddings import embed_passages
from .ingest import _get_or_create_regulation, _get_or_create_regulator, _qdrant_point_id
from .retriever import ensure_collection_exists


@dataclass(frozen=True)
class ArticleSpec:
    """Everything this parser needs to know about one Article-numbered
    regulation's real, rendered text. Built from reading the actual PDF
    (see the module docstring), not inferred from a template."""

    name: str
    noise_exact: frozenset[str]  # whole-line boilerplate (doc control number, domain)
    org_name_substring: str  # filtered wherever it appears, not just whole-line
    page_footer_re: re.Pattern
    preamble_anchor: str  # unique text marking the end of the TOC / start of real content
    article_titles: dict[str, str]  # "1" -> "Terms and Definitions", in TOC order
    annex_start: str  # text marking where the last article's body ends
    annex_header_re: re.Pattern


SASO_ROHS_SPEC = ArticleSpec(
    name="saso_rohs",
    noise_exact=frozenset({"01-09-21-179", "www.saso.gov.sa"}),
    org_name_substring="هيئة المواصفات السعودية",
    page_footer_re=re.compile(r"^Page \d+ of \d+\s*$"),
    preamble_anchor="shall form an integral part thereof.",
    article_titles={
        "1": "Terms and Definitions",
        "2": "Scope",
        "3": "Objectives",
        "4": "Obligations of Supplier",
        "5": "Conformity Assessment Procedures",
        "6": "Responsibilities of Regulatory Authorities",
        "7": "Responsibilities of Market Surveillance Authorities",
        "8": "Violations and penalties",
        "9": "General Provisions",
        "10": "Transitional Provisions",
        "11": "Publication",
    },
    annex_start="Annex (1)",
    annex_header_re=re.compile(r"Annex\s*\((\d+(?:-[a-z])?)\)\s*"),
)

SPECS = {"saso_rohs": SASO_ROHS_SPEC}


# ── Extraction (verified against the real PDF, see module docstring) ──────

def _clean_pages(pdf_path: Path, spec: ArticleSpec) -> list[str]:
    doc = fitz.open(pdf_path)
    pages = []
    try:
        for page in doc:
            kept = []
            for raw_line in page.get_text().split("\n"):
                line = raw_line.strip()
                if not line:
                    continue
                if line in spec.noise_exact:
                    continue
                if spec.org_name_substring in line:
                    continue
                if spec.page_footer_re.match(line):
                    continue
                kept.append(line)
            pages.append(" ".join(kept))
    finally:
        doc.close()
    return pages


def _split_articles(text: str, spec: ArticleSpec) -> list[tuple[str, str]]:
    """Returns [(article_number, body_text)], in document order. Matches
    each real header by its KNOWN title (harvested from the real table of
    contents), not a bare "Article (N)" regex: the document also contains
    inline cross-references to other articles in running prose (e.g.
    "...the measures set forth in Article (8) shall be applied..."), which
    a bare regex cannot tell apart from a real section header. Found live,
    not guessed: an earlier version of this function without the title
    check split one article into two on exactly this kind of reference."""
    found = []
    for num, title in spec.article_titles.items():
        pattern = re.compile(rf"Article\s*\({num}\)\s*{re.escape(title)}")
        m = pattern.search(text)
        if m is None:
            raise ValueError(
                f"Expected header 'Article ({num}) {title}' not found. The real text no longer "
                f"matches this ArticleSpec; re-render the PDF and update article_titles."
            )
        found.append((num, m.start(), m.end()))
    found.sort(key=lambda t: t[1])
    out = []
    for i, (num, _start, end) in enumerate(found):
        body_end = found[i + 1][1] if i + 1 < len(found) else len(text)
        out.append((num, text[end:body_end].strip()))
    return out


def _split_sub_items(article_num: str, body: str) -> list[tuple[str | None, str]]:
    """Returns [(sub_number_or_None, text)] within one article's body.
    A sub-item marker is "<article_num>/<n>" at a word boundary; anchoring
    the article number (not a bare "\\d+/\\d+") keeps a date like
    "30/06/2022" elsewhere in the body from ever being mistaken for one,
    and keeps an article from picking up another article's leftover
    numbering if a split point is slightly off."""
    marker_re = re.compile(rf"(?<!\d)({re.escape(article_num)}/\d{{1,2}})(?=\s)")
    matches = list(marker_re.finditer(body))
    if not matches:
        return [(None, body.strip())]
    items = []
    lead = body[: matches[0].start()].strip()
    if lead:
        items.append(("title", lead))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        items.append((m.group(1).split("/", 1)[1], body[start:end].strip()))
    return items


def parse_clauses(pdf_path: Path, spec: ArticleSpec) -> list[dict]:
    pages = _clean_pages(pdf_path, spec)
    full = " ".join(pages)

    anchor_idx = full.find(spec.preamble_anchor)
    if anchor_idx == -1:
        raise ValueError(f"Preamble anchor {spec.preamble_anchor!r} not found in the extracted text.")
    body_text = full[anchor_idx + len(spec.preamble_anchor):]

    annex_idx = body_text.find(spec.annex_start)
    if annex_idx == -1:
        raise ValueError(f"Annex start marker {spec.annex_start!r} not found after the preamble.")
    articles_text = body_text[:annex_idx]
    annexes_text = body_text[annex_idx:]

    clauses: list[dict] = []
    order = 0
    for article_num, article_body in _split_articles(articles_text, spec):
        title = spec.article_titles[article_num]
        items = _split_sub_items(article_num, article_body)
        sub_items = [(n, t) for n, t in items if n not in (None, "title")]
        if not sub_items:
            # No numbered sub-items (e.g. Article 2 "Scope", Article 11
            # "Publication"): the article itself is the one clause.
            text = " ".join(t for _n, t in items).strip() or title
            clauses.append({
                "clause_id": article_num, "parent_clause_id": None,
                "text_en": f"Article ({article_num}) {title}. {text}".strip(),
                "order_index": order,
            })
            order += 1
            continue
        clauses.append({
            "clause_id": article_num, "parent_clause_id": None,
            "text_en": f"Article ({article_num}) {title}.",
            "order_index": order,
        })
        order += 1
        for sub_num, sub_text in sub_items:
            clause_id = f"{article_num}-{sub_num}"
            clauses.append({
                "clause_id": clause_id, "parent_clause_id": article_num,
                "text_en": sub_text, "order_index": order,
            })
            order += 1

    annex_matches = list(spec.annex_header_re.finditer(annexes_text))
    for i, m in enumerate(annex_matches):
        annex_id = m.group(1)
        if "-" not in annex_id:
            continue  # bare "Annex (1)" / "Annex (2)" group header: no body of its own
        seg_end = annex_matches[i + 1].start() if i + 1 < len(annex_matches) else len(annexes_text)
        seg = annexes_text[m.end():seg_end].strip()
        if not seg:
            continue
        clauses.append({
            "clause_id": f"annex-{annex_id}", "parent_clause_id": None,
            "text_en": f"Annex ({annex_id}). {seg}", "order_index": order,
        })
        order += 1
    # Annex (3) and Annex (4) have no letter suffix, handled the same way
    # as a lettered one here since they are themselves one coherent form,
    # not a further-lettered group like Annex (1)/(2).
    for plain_num in ("3", "4"):
        pattern = re.compile(rf"Annex\s*\({plain_num}\)\s*")
        matches = [mm for mm in re.finditer(pattern, annexes_text)]
        if not matches:
            continue
        m = matches[-1]  # last occurrence: the real header, not a cross-reference
        next_starts = [mm.start() for mm in annex_matches if mm.start() > m.start()]
        seg_end = min(next_starts) if next_starts else len(annexes_text)
        seg = annexes_text[m.end():seg_end].strip()
        if seg and not any(c["clause_id"] == f"annex-{plain_num}" for c in clauses):
            clauses.append({
                "clause_id": f"annex-{plain_num}", "parent_clause_id": None,
                "text_en": f"Annex ({plain_num}). {seg}", "order_index": order,
            })
            order += 1

    return clauses


# ── Write to Postgres + Qdrant (same shape as app/ingest.py's ingest()) ───

def ingest_articles(
    regulator_code: str,
    regulation_code: str,
    version_label: str,
    file_path: Path,
    spec: ArticleSpec,
    replace: bool = False,
) -> None:
    if not file_path.is_file():
        raise SystemExit(f"Source file not found: {file_path}")

    print(f"\n{'='*60}\nXposure: Article-based Regulation Ingestion ({spec.name})")
    print(f"Regulator/Regulation/Version: {regulator_code}/{regulation_code}/{version_label}")
    print(f"File: {file_path}\n{'='*60}")

    import hashlib
    file_bytes = file_path.read_bytes()
    file_sha256 = hashlib.sha256(file_bytes).hexdigest()

    engine = get_engine()
    with Session(engine) as db:
        regulator = _get_or_create_regulator(db, regulator_code)
        regulation = _get_or_create_regulation(db, regulator, regulation_code)

        existing_version = db.scalar(
            select(RegulationVersion).where(
                RegulationVersion.regulation_id == regulation.id,
                RegulationVersion.version_label == version_label,
            )
        )
        if existing_version is not None:
            if not replace:
                raise SystemExit(
                    f"Version '{version_label}' of {regulator_code}/{regulation_code} is already "
                    f"ingested (id={existing_version.id}, {len(existing_version.clauses)} clauses). "
                    f"Pass --replace to delete and re-ingest."
                )
            print(f"[replace] Deleting existing version {existing_version.id} and its clauses...")
            for clause in existing_version.clauses:
                db.delete(clause)
            db.delete(existing_version)
            db.flush()
            _delete_qdrant_version(regulator_code, regulation_code, version_label)

        print("Parsing articles and annexes...")
        parsed = parse_clauses(file_path, spec)
        print(f"  {len(parsed)} clauses")
        if not parsed:
            raise SystemExit("Parsed zero clauses: the ArticleSpec no longer matches this file's real text.")

        version = RegulationVersion(
            regulation_id=regulation.id, version_label=version_label, file_sha256=file_sha256,
        )
        db.add(version)
        db.flush()

        clause_rows = [
            Clause(
                version_id=version.id, clause_id=c["clause_id"], parent_clause_id=c["parent_clause_id"],
                text_en=c["text_en"], order_index=c["order_index"],
            )
            for c in parsed
        ]
        db.add_all(clause_rows)
        db.commit()
        print(f"  Stored in Postgres: regulation_version.id={version.id}, {len(clause_rows)} clause rows")

        print("Embedding + indexing into Qdrant...")
        ensure_collection_exists()
        vectors = embed_passages([c["text_en"] for c in parsed])
        client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
        points = [
            PointStruct(
                id=_qdrant_point_id(regulator_code, regulation_code, version_label, c["clause_id"], "en"),
                vector=vector,
                payload={
                    "regulator": regulator_code, "regulation": regulation_code, "version": version_label,
                    "clause_id": c["clause_id"], "parent_clause_id": c["parent_clause_id"],
                    "lang": "en", "text": c["text_en"], "page": None,
                },
            )
            for c, vector in zip(parsed, vectors)
        ]
        for i in range(0, len(points), 100):
            client.upsert(collection_name=settings.qdrant_collection, points=points[i:i + 100])
        print(f"  Indexed {len(points)} points into '{settings.qdrant_collection}'")

    print(f"\n{'='*60}\nDone.\n{'='*60}\n")


def _delete_qdrant_version(regulator_code: str, regulation_code: str, version_label: str) -> None:
    client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
    client.delete(
        collection_name=settings.qdrant_collection,
        points_selector={
            "filter": {
                "must": [
                    {"key": "regulator", "match": {"value": regulator_code}},
                    {"key": "regulation", "match": {"value": regulation_code}},
                    {"key": "version", "match": {"value": version_label}},
                ]
            }
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest an Article-numbered regulation PDF into Postgres + Qdrant")
    parser.add_argument("--regulator", required=True)
    parser.add_argument("--regulation", required=True)
    parser.add_argument("--version", required=True, dest="version_label")
    parser.add_argument("--spec", required=True, choices=sorted(SPECS))
    parser.add_argument("--file", required=True, dest="file_path", type=Path)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    ingest_articles(
        args.regulator, args.regulation, args.version_label, args.file_path, SPECS[args.spec],
        replace=args.replace,
    )
