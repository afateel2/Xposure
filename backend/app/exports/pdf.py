"""
PDF report, per change — takeoff prompt section 3/M8, reusing the pattern
from ComplyX's `routes/report_pdf.py` (see docs/PLAN.md section 1): build
a static bilingual HTML document, print it to PDF with headless Chromium
via Playwright. Unlike ComplyX's version, which received a client-posted
result it could not fully trust, this one is built entirely from data this
process itself just queried from Postgres — there is no client-supplied
content to verify against a corpus.

Mirrors the real app's shipped palette (frontend/app/globals.css) rather
than inventing report-only colors — plain hex values, kept in step by hand
since this is a standalone HTML document, not a build that can import the
frontend's stylesheet. Updated for the Sept 2026 restyle (see globals.css's
own header comment): warm neutrals, severity-only-gets-color.
"""

import html
import re
from datetime import date

from sqlalchemy.orm import Session

from ..db.models import Change, Clause, Impact, OrgNode, Regulation, RegulationVersion, Regulator

# Mirrors app/diff.py's _SENTENCE_BOUNDARY exactly (see that module for
# why: difference in separator handling would silently mis-highlight a
# clause). Restated rather than imported, same reasoning app/policy.py
# gives for restating app/llm.py's CHANGE_TYPES — this module stays free
# of diff.py's import surface for a report renderer that only needs one
# regex from it.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")

_CHANGE_TYPE_LABEL = {
    "new_obligation": "New obligation", "tightened": "Tightened", "relaxed": "Relaxed",
    "clarification": "Clarification", "editorial": "Editorial", "renumbered": "Renumbered",
    "withdrawn": "Withdrawn",
}
_BAND_COLOR_VAR = {"critical": "--critical", "high": "--high", "medium": "--medium", "low": "--low"}


def _e(text: str | None) -> str:
    return html.escape(text or "")


def _split_sentences(text: str) -> list[str]:
    if not text:
        return []
    return [s.strip() for s in _SENTENCE_BOUNDARY.split(text) if s.strip()]


def _quote_block(label: str, text: str | None, changed: set[str], empty_msg: str) -> str:
    if not text:
        return f'<div class="quote"><div class="quote-label">{_e(label)}</div><p class="quote-empty">{_e(empty_msg)}</p></div>'
    sentences = _split_sentences(text)
    body = " ".join(
        f"<mark>{_e(s)}</mark>" if s in changed else _e(s)
        for s in sentences
    )
    return f'<div class="quote"><div class="quote-label">{_e(label)}</div><p class="quote-text">{body}</p></div>'


def build_change_report_html(
    db: Session,
    change: Change,
    *,
    priority_score: int,
    priority_band: str,
) -> str:
    regulation = db.get(Regulation, change.regulation_id)
    regulator = db.get(Regulator, regulation.regulator_id)
    from_version = db.get(RegulationVersion, change.from_version_id)
    to_version = db.get(RegulationVersion, change.to_version_id)

    old_clause = (
        db.query(Clause).filter_by(version_id=change.from_version_id, clause_id=change.old_clause_id).first()
        if change.old_clause_id else None
    )
    new_clause = (
        db.query(Clause).filter_by(version_id=change.to_version_id, clause_id=change.new_clause_id).first()
        if change.new_clause_id else None
    )

    ops = (change.diff_spans_json or {}).get("ops", [])
    old_changed = {s for op in ops for s in op.get("old", [])}
    new_changed = {s for op in ops for s in op.get("new", [])}

    old_block = _quote_block(
        f"Previous text · {from_version.version_label if from_version else '?'}",
        old_clause.text_en if old_clause else None, old_changed,
        "[no counterpart in the old version]",
    )
    new_block = _quote_block(
        f"New text · {to_version.version_label if to_version else '?'}",
        new_clause.text_en if new_clause else None, new_changed,
        "[no counterpart in the new version]",
    )

    impacts = list(db.query(Impact).filter_by(change_id=change.id).order_by(Impact.id).all())
    impact_rows = "".join(
        f"""<tr>
          <td><span class="node-type">{_e(node.type if node else "?")}</span><br><strong>{_e(node.name if node else "?")}</strong></td>
          <td>{_e(impact.path_json.get("summary", "") if impact.path_json else "")}</td>
          <td>{_e(impact.note_en)}</td>
          <td>{", ".join(_e(a) for a in (impact.recommended_actions_json or []))}</td>
        </tr>"""
        for impact in impacts
        for node in [db.get(OrgNode, impact.node_id)]
    ) or '<tr><td colspan="4" class="empty">No impacted nodes matched in the current org graph.</td></tr>'

    band_var = _BAND_COLOR_VAR.get(priority_band, "--medium")
    type_label = _CHANGE_TYPE_LABEL.get(change.change_type or "", change.change_type or "unclassified")
    clause_ref = change.new_clause_id or change.old_clause_id or ""

    return f"""<!doctype html>
<html lang="en" dir="ltr">
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans+Arabic:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  /* Values only, variable NAMES kept as every rule below already
     references them — the same repaint-by-token-swap technique
     frontend/app/globals.css's own header comment documents, applied
     here so this report matches the real app (xposure-style-guide.html,
     Sept 2026: warm neutrals, colour means severity and nothing else). */
  :root {{
    --bg: #EDECE9; --surface: #FFFFFF; --surface-2: #EDECE9;
    --border: #C9C6C1; --ink: #1F1D1B; --ink-muted: #3A3531; --ink-faint: #6E6862;
    --accent: #17548F; --accent-wash: #E6EFF8;
    --critical: #A31E17; --critical-wash: #FAE9E7;
    --high: #955000; --high-wash: #FBF0E0;
    --medium: #6F5D00; --medium-wash: #F6F2DC;
    --low: #6E6862; --low-wash: #EAE8E4;
  }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: "IBM Plex Sans Arabic", Arial, sans-serif; color: var(--ink); margin: 0; font-size: 11px; line-height: 1.6; background: var(--bg); }}
  .font-mono {{ font-family: "IBM Plex Mono", monospace; }}
  header {{ padding: 30px 42px 20px; border-bottom: 2px solid var(--ink); }}
  .brand {{ font-family: "IBM Plex Sans Arabic", Arial, sans-serif; font-weight: 600; font-size: 18px; margin-bottom: 14px; }}
  .kicker {{ font-size: 10px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink-faint); }}
  h1 {{ font-size: 20px; margin: 4px 0 10px; }}
  .badges {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
  .badge {{ font-size: 10px; font-weight: 700; padding: 3px 10px; border-radius: 999px; background: var({band_var}-wash); color: var({band_var}); }}
  .badge.type {{ background: var(--surface-2); color: var(--ink-muted); border: 1px solid var(--border); }}
  .meta-row {{ margin-top: 10px; font-size: 10.5px; color: var(--ink-faint); display: flex; gap: 16px; flex-wrap: wrap; }}
  main {{ padding: 22px 42px 30px; }}
  .section-title {{ font-size: 10px; font-weight: 700; letter-spacing: 0.07em; text-transform: uppercase; color: var(--ink-faint); margin: 22px 0 8px; }}
  .quote-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
  .quote {{ background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 10px 13px; }}
  .quote-label {{ font-size: 9.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-faint); margin-bottom: 6px; }}
  .quote-text {{ margin: 0; font-size: 10.5px; }}
  .quote-empty {{ margin: 0; font-size: 10.5px; font-style: italic; color: var(--ink-faint); }}
  mark {{ background: var(--accent-wash); color: var(--ink); border-radius: 2px; padding: 0 2px; }}
  .summary {{ font-size: 12px; line-height: 1.65; border-inline-start: 3px solid var(--accent); padding-inline-start: 12px; margin: 6px 0; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 10px; margin-top: 4px; }}
  th {{ text-align: left; font-size: 9px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-faint); border-bottom: 2px solid var(--ink); padding: 6px 8px; }}
  td {{ border-bottom: 1px solid var(--border); padding: 8px; vertical-align: top; }}
  .node-type {{ font-family: "IBM Plex Mono", monospace; font-size: 8.5px; color: var(--ink-faint); text-transform: uppercase; }}
  .empty {{ text-align: center; color: var(--ink-faint); font-style: italic; }}
  .citation {{ margin-top: 20px; padding-top: 12px; border-top: 1px dashed var(--border); font-size: 9.5px; color: var(--ink-faint); display: flex; gap: 18px; flex-wrap: wrap; }}
  .citation b {{ color: var(--ink-muted); }}
</style>
</head>
<body>
  <header>
    <div class="brand">Xposure</div>
    <div class="kicker">Regulatory change report</div>
    <h1>{_e(change.summary_en)}</h1>
    <div class="badges">
      <span class="badge">{_e(priority_band.upper())} · {priority_score}/100</span>
      <span class="badge type">{_e(type_label)}</span>
      <span class="font-mono" style="font-size:10.5px;color:var(--ink-muted)">{_e(clause_ref)}</span>
    </div>
    <div class="meta-row">
      <span><b>Regulator</b> {_e(regulator.name_en)}</span>
      <span><b>Regulation</b> {_e(regulation.title_en)}</span>
      {f'<span><b>Effective</b> {change.effective_date.isoformat()}</span>' if change.effective_date else ""}
      <span><b>Confidence</b> {round((change.confidence or 0) * 100)}%</span>
      <span><b>Generated</b> {date.today().isoformat()}</span>
    </div>
  </header>
  <main>
    <div class="section-title">Diff receipt</div>
    <div class="quote-grid">{old_block}{new_block}</div>

    <div class="section-title">Summary</div>
    <p class="summary">{_e(change.summary_en)}</p>

    <div class="section-title">Impacted nodes ({len(impacts)})</div>
    <table>
      <thead><tr><th>Node</th><th>Path</th><th>Note</th><th>Recommended actions</th></tr></thead>
      <tbody>{impact_rows}</tbody>
    </table>

    <div class="citation">
      <span><b>{_e(from_version.version_label if from_version else "")}</b> p.{old_clause.page_en if old_clause else "-"} · {_e(from_version.file_sha256 if from_version else "")}</span>
      <span><b>{_e(to_version.version_label if to_version else "")}</b> p.{new_clause.page_en if new_clause else "-"} · {_e(to_version.file_sha256 if to_version else "")}</span>
      <span><b>Match</b> {_e(change.match_kind)}</span>
    </div>
  </main>
</body>
</html>"""


def render_change_pdf(db: Session, change: Change, *, priority_score: int, priority_band: str) -> bytes:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "PDF export requires Playwright: pip install playwright && playwright install chromium"
        ) from exc

    html_doc = build_change_report_html(db, change, priority_score=priority_score, priority_band=priority_band)
    clause_ref = change.new_clause_id or change.old_clause_id or str(change.id)
    footer = (
        '<div style="width:100%; font-size:8.5px; color:#65777d; padding:0 42px; '
        'display:flex; justify-content:space-between; font-family: Arial, sans-serif;">'
        f'<span>Xposure · {html.escape(clause_ref)}</span>'
        '<span><span class="pageNumber"></span>/<span class="totalPages"></span></span></div>'
    )
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            try:
                page.set_content(html_doc, wait_until="networkidle", timeout=8000)
            except Exception:
                pass  # fonts unreachable; already-set content renders with the fallback stack
            pdf_bytes = page.pdf(
                format="A4",
                print_background=True,
                display_header_footer=True,
                header_template="<span></span>",
                footer_template=footer,
                margin={"top": "10mm", "bottom": "14mm", "left": "0", "right": "0"},
            )
        finally:
            browser.close()
    return pdf_bytes


def pdf_filename(change: Change) -> str:
    clause = (change.new_clause_id or change.old_clause_id or str(change.id)).replace("/", "-")
    return f"xposure-change-{change.id}-{clause}-{date.today().isoformat()}.pdf"
