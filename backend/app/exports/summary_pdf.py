"""
PDF report, aggregate across many changes — the executive-summary export
that sits alongside app/exports/pdf.py's per-change report. Same rendering
pattern (static HTML, printed to PDF with headless Chromium via Playwright)
fed by aggregate data instead of one change's diff receipt, so this module
mirrors pdf.py's shape deliberately rather than inventing a new one: same
_e() escaping discipline (real LLM-generated summaries and regulator names
flow into this HTML), same deferred Playwright import, same design tokens.

Priority is recomputed per change via routes/changes.py's
compute_priority_for_change rather than threaded through as an argument:
that module's own docstring already establishes recomputing the pure,
deterministic priority.compute_priority() wherever it's needed is cheap
and gives the exact same number every time, so there is nothing to gain
by having callers resolve it first and pass it down.
"""

from collections import Counter
from datetime import date

from sqlalchemy.orm import Session

from ..db.models import Change, Regulation, Regulator
from ..routes.changes import compute_priority_for_change
from .pdf import _e, _split_sentences

# Restated in miniature from pdf.py's _CHANGE_TYPE_LABEL rather than
# imported — that dict is private to the per-change renderer, and this
# report only needs display labels, not the rest of that module's import
# surface (same reasoning pdf.py itself gives for restating diff.py's
# sentence-boundary regex instead of importing it).
_CHANGE_TYPE_LABEL = {
    "new_obligation": "New obligation", "tightened": "Tightened", "relaxed": "Relaxed",
    "clarification": "Clarification", "editorial": "Editorial", "renumbered": "Renumbered",
    "withdrawn": "Withdrawn",
}
_BAND_ORDER = ("critical", "high", "medium", "low")
_BAND_COLOR_VAR = {"critical": "--critical", "high": "--high", "medium": "--medium", "low": "--low"}

TOP_N = 20


def _regulation_and_regulator(
    db: Session, change: Change, cache: dict[int, tuple[Regulation | None, Regulator | None]]
) -> tuple[Regulation | None, Regulator | None]:
    if change.regulation_id not in cache:
        regulation = db.get(Regulation, change.regulation_id)
        regulator = db.get(Regulator, regulation.regulator_id) if regulation else None
        cache[change.regulation_id] = (regulation, regulator)
    return cache[change.regulation_id]


def _filters_summary_html(filters: dict) -> str:
    regulator = filters.get("regulator")
    since = filters.get("since")
    band = filters.get("band")
    return " &nbsp;·&nbsp; ".join([
        f"<b>Regulator</b> {_e(str(regulator)) if regulator else 'All'}",
        f"<b>Since</b> {_e(str(since)) if since else 'All time'}",
        f"<b>Band</b> {_e(str(band).upper()) if band else 'All'}",
    ])


def build_summary_report_html(db: Session, changes: list[Change], *, filters: dict) -> str:
    reg_cache: dict[int, tuple[Regulation | None, Regulator | None]] = {}
    scored: list[tuple[Change, int, str, Regulation | None, Regulator | None]] = []
    for change in changes:
        score, band = compute_priority_for_change(db, change)
        regulation, regulator = _regulation_and_regulator(db, change, reg_cache)
        scored.append((change, score, band, regulation, regulator))
    scored.sort(key=lambda row: row[1], reverse=True)

    band_counts = Counter(band for _, _, band, _, _ in scored)
    type_counts = Counter((change.change_type or "unclassified") for change, _, _, _, _ in scored)
    regulator_counts = Counter((regulator.name_en if regulator else "Unknown") for *_, regulator in scored)

    band_tiles = "".join(
        f"""<div class="tile">
          <div class="tile-value" style="color:var({_BAND_COLOR_VAR[b]})">{band_counts.get(b, 0)}</div>
          <div class="tile-label">{_e(b)}</div>
        </div>"""
        for b in _BAND_ORDER
    )

    type_rows = "".join(
        f"""<tr><td>{_e(_CHANGE_TYPE_LABEL.get(t, t))}</td><td class="num">{n}</td></tr>"""
        for t, n in sorted(type_counts.items(), key=lambda kv: kv[1], reverse=True)
    ) or '<tr><td colspan="2" class="empty">No changes matched.</td></tr>'

    regulator_rows = "".join(
        f"""<tr><td>{_e(name)}</td><td class="num">{n}</td></tr>"""
        for name, n in sorted(regulator_counts.items(), key=lambda kv: kv[1], reverse=True)
    ) or '<tr><td colspan="2" class="empty">No changes matched.</td></tr>'

    top_rows = "".join(
        f"""<tr>
          <td class="font-mono">{_e(change.new_clause_id or change.old_clause_id or str(change.id))}</td>
          <td>{_e(regulator.name_en if regulator else "?")}</td>
          <td>{_e(_CHANGE_TYPE_LABEL.get(change.change_type or "", change.change_type or "unclassified"))}</td>
          <td><span class="badge" style="background:var({_BAND_COLOR_VAR.get(band, '--medium')}-wash);color:var({_BAND_COLOR_VAR.get(band, '--medium')})">{_e(band.upper())} · {score}</span></td>
          <td>{_e((_split_sentences(change.summary_en) or [""])[0]) or "[no summary]"}</td>
          <td>{change.effective_date.isoformat() if change.effective_date else "-"}</td>
        </tr>"""
        for change, score, band, regulation, regulator in scored[:TOP_N]
    ) or '<tr><td colspan="6" class="empty">No changes matched the applied filters.</td></tr>'

    return f"""<!doctype html>
<html lang="en" dir="ltr">
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans+Arabic:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  /* Values only, variable NAMES kept as every rule below already
     references them — same technique as app/exports/pdf.py (see that
     file's comment) and frontend/app/globals.css's own header comment:
     matches the real app's palette (xposure-style-guide.html, Sept 2026). */
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
  .filters {{ margin-top: 10px; font-size: 10.5px; color: var(--ink-faint); }}
  main {{ padding: 22px 42px 30px; }}
  .section-title {{ font-size: 10px; font-weight: 700; letter-spacing: 0.07em; text-transform: uppercase; color: var(--ink-faint); margin: 22px 0 8px; }}
  .tiles {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }}
  .tile {{ background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 12px 14px; text-align: center; }}
  .tile-value {{ font-size: 22px; font-weight: 700; }}
  .tile-label {{ font-size: 9.5px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-faint); margin-top: 2px; }}
  .split {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 10px; margin-top: 4px; }}
  th {{ text-align: left; font-size: 9px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-faint); border-bottom: 2px solid var(--ink); padding: 6px 8px; }}
  td {{ border-bottom: 1px solid var(--border); padding: 8px; vertical-align: top; }}
  td.num {{ text-align: right; font-family: "IBM Plex Mono", monospace; }}
  .badge {{ font-size: 9.5px; font-weight: 700; padding: 2px 8px; border-radius: 999px; white-space: nowrap; }}
  .empty {{ text-align: center; color: var(--ink-faint); font-style: italic; }}
  .total {{ font-size: 10.5px; color: var(--ink-faint); margin-bottom: 10px; }}
  .total b {{ color: var(--ink); font-size: 13px; }}
</style>
</head>
<body>
  <header>
    <div class="brand">Xposure</div>
    <div class="kicker">Executive summary: regulatory change report</div>
    <h1>Aggregate change report</h1>
    <div class="filters">{_filters_summary_html(filters)}</div>
  </header>
  <main>
    <div class="total">Total changes matching filters: <b>{len(scored)}</b> · Generated {date.today().isoformat()}</div>

    <div class="section-title">Counts by priority band</div>
    <div class="tiles">{band_tiles}</div>

    <div class="split">
      <div>
        <div class="section-title">Counts by change type</div>
        <table>
          <thead><tr><th>Type</th><th class="num">Count</th></tr></thead>
          <tbody>{type_rows}</tbody>
        </table>
      </div>
      <div>
        <div class="section-title">Counts by regulator</div>
        <table>
          <thead><tr><th>Regulator</th><th class="num">Count</th></tr></thead>
          <tbody>{regulator_rows}</tbody>
        </table>
      </div>
    </div>

    <div class="section-title">Top {TOP_N} changes by priority</div>
    <table>
      <thead><tr><th>Clause</th><th>Regulator</th><th>Type</th><th>Priority</th><th>Summary</th><th>Effective</th></tr></thead>
      <tbody>{top_rows}</tbody>
    </table>
  </main>
</body>
</html>"""


def render_summary_pdf(db: Session, changes: list[Change], *, filters: dict) -> bytes:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "PDF export requires Playwright: pip install playwright && playwright install chromium"
        ) from exc

    html_doc = build_summary_report_html(db, changes, filters=filters)
    footer = (
        '<div style="width:100%; font-size:8.5px; color:#65777d; padding:0 42px; '
        'display:flex; justify-content:space-between; font-family: Arial, sans-serif;">'
        f'<span>Xposure · Executive summary · {len(changes)} changes</span>'
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


def summary_pdf_filename(filters: dict) -> str:
    # Filter values are not embedded here (unlike pdf_filename's clause
    # ref): an arbitrary regulator/since/band combination doesn't make a
    # clean filename, and this report is date-stamped like any other
    # on-demand export, so the date alone is enough to distinguish runs.
    return f"xposure-summary-{date.today().isoformat()}.pdf"
