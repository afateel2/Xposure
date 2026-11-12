"""
app/citation.py: is a clause's text really in the stored source file?

Real PDFs are generated on the fly with PyMuPDF (no fixtures to go stale), so
each case states exactly what is on which page.
"""

import hashlib

import fitz
import pytest

from app import citation

LONG = "The entity must implement protection against distributed denial of service attacks on its public services."


def make_pdf(path, pages):
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(40, 40, 550, 800), text, fontsize=11)
    doc.save(str(path))
    doc.close()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_normalize_ignores_case_spacing_and_punctuation_but_keeps_word_order():
    assert citation.normalize("Multi-factor  Authentication, (MFA).") == citation.normalize("multi factor authentication MFA")
    assert citation.normalize("a b") != citation.normalize("b a")
    assert citation.normalize(None) == ""


def test_found_on_the_cited_page_is_verified(tmp_path):
    pdf = tmp_path / "a.pdf"
    sha = make_pdf(pdf, ["Page one filler.", f"Intro. {LONG} Outro."])
    result = citation.check_clause_text(pdf, sha, LONG, cited_page=2)
    assert (result.status, result.page, result.cited_page, result.file_hash_ok) == ("verified", 2, 2, True)


def test_line_wraps_and_dash_styles_do_not_break_a_match(tmp_path):
    pdf = tmp_path / "a.pdf"
    sha = make_pdf(pdf, ["Multi-factor authentication for remote access\nand for privileged accounts, as required."])
    result = citation.check_clause_text(pdf, sha, "Multi factor authentication for remote access and for privileged accounts", cited_page=1)
    assert result.status == "verified"


def test_found_on_a_different_page_is_reported_with_both_pages(tmp_path):
    pdf = tmp_path / "a.pdf"
    sha = make_pdf(pdf, ["Nothing relevant here.", f"Elsewhere. {LONG}"])
    result = citation.check_clause_text(pdf, sha, LONG, cited_page=1)
    assert (result.status, result.page, result.cited_page) == ("other_page", 2, 1)


def test_short_text_on_another_page_proves_nothing(tmp_path):
    pdf = tmp_path / "a.pdf"
    sha = make_pdf(pdf, ["Unrelated.", "Cybersecurity policies appear in many places."])
    result = citation.check_clause_text(pdf, sha, "Cybersecurity policies", cited_page=1)
    assert result.status == "not_found"  # below MIN_ELSEWHERE_CHARS, so no whole-document search


def test_text_that_is_not_in_the_file_is_not_found(tmp_path):
    pdf = tmp_path / "a.pdf"
    sha = make_pdf(pdf, ["Something else entirely."])
    assert citation.check_clause_text(pdf, sha, LONG, cited_page=1).status == "not_found"


def test_words_in_the_wrong_order_are_not_a_match(tmp_path):
    pdf = tmp_path / "a.pdf"
    sha = make_pdf(pdf, ["denial of service attacks on its public services distributed protection against"])
    assert citation.check_clause_text(pdf, sha, LONG, cited_page=1).status == "not_found"


def test_a_file_that_no_longer_matches_its_recorded_hash_is_flagged_before_anything_else(tmp_path):
    pdf = tmp_path / "a.pdf"
    make_pdf(pdf, [LONG])
    result = citation.check_clause_text(pdf, "0" * 64, LONG, cited_page=1)
    assert (result.status, result.file_hash_ok) == ("file_changed", False)


@pytest.mark.parametrize("clause_text", [None, "", "   ", "-- .. --"])
def test_nothing_to_check_is_unavailable(tmp_path, clause_text):
    pdf = tmp_path / "a.pdf"
    sha = make_pdf(pdf, [LONG])
    result = citation.check_clause_text(pdf, sha, clause_text, cited_page=1)
    assert (result.status, result.reason) == ("unavailable", "no clause text to check")


def test_missing_or_unreadable_files_are_unavailable_never_an_exception(tmp_path):
    assert citation.check_clause_text(None, "x", LONG, 1).reason == "source file not found"
    assert citation.check_clause_text(tmp_path / "missing.pdf", "x", LONG, 1).status == "unavailable"
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"this is not a pdf")
    result = citation.check_clause_text(broken, None, LONG, 1)
    assert result.status == "unavailable" and result.reason.startswith("could not read file")


def test_replacing_the_file_is_noticed_not_served_from_cache(tmp_path):
    pdf = tmp_path / "a.pdf"
    first_sha = make_pdf(pdf, [LONG])
    assert citation.check_clause_text(pdf, first_sha, LONG, 1).status == "verified"
    second_sha = make_pdf(pdf, ["Now it says something completely different, and quite a bit longer than before."])
    assert citation.check_clause_text(pdf, second_sha, LONG, 1).status == "not_found"
    assert citation.check_clause_text(pdf, first_sha, LONG, 1).status == "file_changed"
