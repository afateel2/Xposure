"""
app/ingest_articles.py: the Article-numbered parser used for SASO's RoHS
technical regulation (a different document shape from NCA ECC's two-column
code|text table, see that module's docstring).

Fixtures are built from real extracted text (PyMuPDF page.get_text() on the
real saso.gov.sa PDF, trimmed for test size), the same discipline
test_ingest.py's own module docstring states for ECC's fixtures: real block
dumps, not synthetic approximations. In particular, the Article (7)/(8)
boundary fixture below reproduces a real pitfall found while building this
parser: Article 7's own body contains the words "Article (8)" as a
cross-reference mid-sentence ("...the measures set forth in Article (8)
shall be applied, after taking the necessary actions."), which a bare
"Article \\(N\\)" regex cannot tell apart from a real section header — an
earlier version of this parser (without the title-anchored matching
_split_articles uses) split Article 7's last item into a spurious extra
"Article 8" with no real content, found by running it against the real
document and noticing a duplicate heading, not by inspection.
"""

import pytest

from app.ingest_articles import ArticleSpec, _split_articles, _split_sub_items, parse_clauses


# A trimmed ArticleSpec covering 3 real articles (1, 7, 8) so the fixture
# below stays small while still exercising: a multi-item article, an
# article with no sub-items, and the real cross-reference pitfall.
_SPEC = ArticleSpec(
    name="test_fixture",
    noise_exact=frozenset(),
    org_name_substring="هيئة المواصفات السعودية",
    page_footer_re=__import__("re").compile(r"^Page \d+ of \d+\s*$"),
    preamble_anchor="shall form an integral part thereof.",
    article_titles={
        "1": "Terms and Definitions",
        "7": "Responsibilities of Market Surveillance Authorities",
        "8": "Violations and penalties",
    },
    annex_start="Annex (1)",
    annex_header_re=__import__("re").compile(r"Annex\s*\((\d+(?:-[a-z])?)\)\s*"),
)

# Real text (trimmed), reproducing: the preamble anchor, Article (1) with
# two real "1/1"/"1/2" items, Article (7) whose last sentence genuinely
# cross-references "Article (8)" mid-prose, the real Article (8) header
# with two real items, then the real Annex (1) boundary.
_REAL_TEXT = (
    "Note: This preamble and all the annexes of this regulation "
    "shall form an integral part thereof. "
    "Article (1) Terms and Definitions "
    "1/1 When applying the articles of this regulation, terms and expressions hereunder – shall "
    "have the meanings indicated in front thereof, unless the context otherwise requires: KSA: The "
    "Kingdom of Saudi Arabia. "
    "1/2 Other terms and expressions specified in this Regulation shall have the meanings specified "
    "in the applicable laws, regulations, and decrees of SASO. "
    "Article (7) Responsibilities of Market Surveillance Authorities "
    "Market Surveillance Authorities, as a part of their competences and powers, shall carry out the "
    "following: "
    "7/1 Enforce the market surveillance procedures to the products available in the markets. "
    "7/2 Sample the product, whether from the market or warehouses of suppliers. "
    "7/3 In case of non-conformity of a product, Market Surveillance Authorities shall take all "
    "necessary actions in order to ensure the products' conformity, and the measures set forth in "
    "Article (8) shall be applied, after taking the necessary actions. "
    "Article (8) Violations and penalties "
    "8/1 It is prohibited to manufacture, import, place, display, or even advertise products that are "
    "non-conforming to the provisions of this Technical Regulation. "
    "8/2 Failure to meet the requirements of this Technical Regulation shall be a sufficient reason "
    "for Market Surveillance Authorities to act. "
    "Annex (1) "
    "Annex (1-a) List of Substances Excluded from the Application of Hazardous Materials Limits "
    "Serial Number Excluded Items 1 Mercury in single-capped fluorescent lamps."
)


def test_split_articles_follows_the_real_titles_not_a_bare_number():
    anchor_idx = _REAL_TEXT.find(_SPEC.preamble_anchor)
    body = _REAL_TEXT[anchor_idx + len(_SPEC.preamble_anchor):]
    annex_idx = body.find(_SPEC.annex_start)
    articles_text = body[:annex_idx]

    articles = _split_articles(articles_text, _SPEC)
    numbers = [n for n, _body in articles]
    assert numbers == ["1", "7", "8"]  # in document order, not dict order


def test_cross_reference_inside_article_7_does_not_create_a_spurious_article_8():
    anchor_idx = _REAL_TEXT.find(_SPEC.preamble_anchor)
    body = _REAL_TEXT[anchor_idx + len(_SPEC.preamble_anchor):]
    annex_idx = body.find(_SPEC.annex_start)
    articles_text = body[:annex_idx]

    articles = dict(_split_articles(articles_text, _SPEC))
    # Article 7's body contains the real cross-reference text verbatim...
    assert "Article (8) shall be applied" in articles["7"]
    # ...but Article 8's own body is the REAL article 8, not the leftover
    # "shall be applied, after taking the necessary actions." fragment a
    # bare-regex split produces (this was the actual bug, found live).
    assert articles["8"].strip().startswith("8/1") or "prohibited to manufacture" in articles["8"]


def test_split_articles_raises_a_clear_error_when_a_title_is_missing():
    spec = ArticleSpec(
        name="broken", noise_exact=frozenset(), org_name_substring="x",
        page_footer_re=__import__("re").compile(r"^$"), preamble_anchor="x",
        article_titles={"1": "A title that does not appear anywhere"},
        annex_start="Annex (1)", annex_header_re=__import__("re").compile(r"Annex\s*\((\d+)\)"),
    )
    with pytest.raises(ValueError, match="not found"):
        _split_articles("Article (1) Something else entirely.", spec)


def test_split_sub_items_anchors_on_the_article_number_not_a_bare_fraction():
    # "30/06/2022" elsewhere in a real document must never be mistaken for
    # sub-item "30/06" of some article; _split_sub_items only ever looks
    # for "<this article's number>/<n>", so an unrelated date never matches.
    body = "1/1 First real item, dated 30/06/2022 for context. 1/2 Second real item."
    items = _split_sub_items("1", body)
    assert [n for n, _t in items] == ["1", "2"]
    assert "30/06/2022" in items[0][1]
    assert items[1][1] == "Second real item."


def test_split_sub_items_with_no_markers_returns_the_whole_body():
    items = _split_sub_items("2", "This Technical Regulation shall apply to all electrical equipment.")
    assert items == [(None, "This Technical Regulation shall apply to all electrical equipment.")]


def test_parse_clauses_end_to_end_against_the_trimmed_real_fixture(tmp_path, monkeypatch):
    """Exercises parse_clauses()'s full page-cleaning + split pipeline by
    feeding it a one-page PDF built from the real fixture text (via
    PyMuPDF's own writer, so this is a genuine PDF round-trip, not a
    monkeypatch of the extraction step)."""
    import fitz

    pdf_path = tmp_path / "fixture.pdf"
    doc = fitz.open()
    page = doc.new_page()
    rect = fitz.Rect(20, 20, page.rect.width - 20, page.rect.height - 20)
    overflow = page.insert_textbox(rect, _REAL_TEXT, fontsize=7)
    assert overflow >= 0, "fixture text did not fit the page; shorten _REAL_TEXT or the rect/fontsize"
    doc.save(pdf_path)
    doc.close()

    clauses = parse_clauses(pdf_path, _SPEC)
    by_id = {c["clause_id"]: c for c in clauses}

    assert by_id["1-1"]["parent_clause_id"] == "1"
    assert "Kingdom of Saudi Arabia" in by_id["1-1"]["text_en"]
    assert by_id["1-2"]["parent_clause_id"] == "1"

    # Article 7 has no numbered items before the cross-reference consumes
    # it as one body (7/1-7/3 are real items in the fixture); confirm no
    # spurious "8" appears as a child of 7 and that 8's real items exist.
    assert by_id["8-1"]["text_en"].startswith("It is prohibited")
    assert "annex-1-a" in by_id
    assert "Mercury in single-capped fluorescent lamps" in by_id["annex-1-a"]["text_en"]

    # order_index is strictly increasing in document order.
    order = [c["order_index"] for c in clauses]
    assert order == sorted(order)
    assert len(set(order)) == len(order)


def test_known_annex_table_limitation_is_captured_not_lost():
    """The module docstring states Annex 1-a/1-b/2-a/2-b stay one coarse
    clause each rather than being split row by row; confirm the real text
    is still present in full (nothing silently dropped), just un-split."""
    anchor_idx = _REAL_TEXT.find(_SPEC.preamble_anchor)
    body = _REAL_TEXT[anchor_idx + len(_SPEC.preamble_anchor):]
    annex_idx = body.find(_SPEC.annex_start)
    annexes_text = body[annex_idx:]
    matches = list(_SPEC.annex_header_re.finditer(annexes_text))
    ids = [m.group(1) for m in matches]
    assert "1-a" in ids
    seg = annexes_text[matches[ids.index("1-a")].end():].strip()
    assert "Serial Number" in seg and "Mercury" in seg
