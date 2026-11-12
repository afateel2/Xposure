from app.ingest import parse_ecc_clauses

# Built directly from real `page.get_text("blocks")` dumps of both source
# PDFs (see ingest.py's module docstring), not synthetic approximations —
# ECC-1:2018 page 21 ("Networks Security Management") and ECC-2:2024 page
# 18 ("Cybersecurity Risk Management"). The two conventions are opposite:
# ECC-1 blocks put a row's TEXT before its CODE; ECC-2 blocks put the CODE
# first, and its dotted subcontrols are inline-prefixed on one line.

_TEXT_BEFORE_CODE_BLOCKS = [
    {"page": 21, "text": "Networks Security Management\n2-5\n"},
    {"page": 21, "text": "To ensure the protection of organization's network from cyber risks.\nObjective\n"},
    {"page": 21, "text": "Controls\n"},
    {"page": 21, "text": "Cybersecurity requirements for network security management must be defined, documented and \napproved.\n2-5-1\n"},
    {"page": 21, "text": "The cybersecurity requirements for network security management must be implemented.\n2-5-2\n"},
    {"page": 21, "text": "The cybersecurity requirements for network security management must include at least the \n"},
    {"page": 21, "text": "following: \n"},
    {"page": 21, "text": "Logical or physical segregation and segmentation of network segments using \n"},
    {"page": 21, "text": "firewalls and defense-in-depth principles. \n"},
    {"page": 21, "text": "2-5-3-1 \n"},
    {"page": 22, "text": "Network segregation between production, test and development environments. \n2-5-3-2 \n"},
    {"page": 22, "text": "2-5-3\n"},
    {"page": 22, "text": "The cybersecurity requirements for network security management must be reviewed periodically.\n2-5-4\n"},
]

_CODE_BEFORE_TEXT_BLOCKS = [
    {"page": 18, "text": "1-5 \nCybersecurity Risk Management \nObjective To ensure managing cybersecurity risks in a methodological approach, in order to \n"},
    {"page": 18, "text": (
        "protect the entity's information and technology assets, as per the entity's regulatory \n"
        "policies and procedures and the relevant legislative and regulatory requirements. \n"
        "Controls \n1-5-1 \n"
        "The cybersecurity department of the entity shall identify, document, and approve the \n"
        "cybersecurity risk management methodology and procedures within the entity, in \n"
        "accordance with considerations of confidentiality, and the integrity and availability of \n"
        "information and technology assets.  \n"
        "1-5-2 \n"
        "The cybersecurity department shall implement the cybersecurity risk management \n"
        "methodology and procedures within the entity.  \n"
    )},
    {"page": 18, "text": "1-5-3 \n"},
    {"page": 18, "text": (
        "The cybersecurity risk assessment procedures shall be implemented at least in the \n"
        "following cases:  \n"
        "1.5.3.1 At early stage of technology projects.  \n"
        "1.5.3.2 Before making major changes to technology infrastructure.   \n"
        "1.5.3.3 During planning to obtain third party services. \n"
        "1.5.3.4 During planning and before the release of new technology services and products.\n"
    )},
    {"page": 18, "text": (
        "1-5-4 \nThe cybersecurity risk management methodology and procedures shall be reviewed and \n"
        "updated at planned intervals (or in case of changes to the relevant legislative and \n"
        "regulatory requirements and standards). Changes shall be documented and approved.   \n"
        "1-6\nCybersecurity in Information and Technology Project Management  \n"
    )},
    {"page": 19, "text": "Objective\n"},
    {"page": 19, "text": (
        "To ensure that cybersecurity requirements are included in the methodology and \n"
        "procedures of the entity's project management, in order to protect the confidentiality, \n"
        "integrity, accuracy, and availability of the entity's information and technology assets, \n"
        "as per the entity's regulatory policies and procedures and the relevant legislative and \n"
        "regulatory requirements. \nControls \n"
    )},
    {"page": 19, "text": "1-6-1 \n"},
    {"page": 19, "text": (
        "Cybersecurity requirements shall be included in the project management methodology \n"
        "and procedures and in the information and technology asset change management \n"
        "within the entity to ensure identifying and managing cybersecurity risks as part of the \n"
        "technology project lifecycle. The cybersecurity requirements shall be a key part of the \n"
        "requirements for technology projects. \n"
    )},
]


# ── text-before-code (ECC-1:2018) ────────────────────────────────────────

def test_text_before_code_simple_control():
    clauses = parse_ecc_clauses(_TEXT_BEFORE_CODE_BLOCKS, code_before_text=False)
    by_id = {c["clause_id"]: c for c in clauses}
    assert by_id["2-5-1"]["text_en"] == (
        "Cybersecurity requirements for network security management must be defined, "
        "documented and approved."
    )
    assert by_id["2-5-1"]["parent_clause_id"] == "2-5"


def test_text_before_code_domain_row_has_no_parent():
    clauses = parse_ecc_clauses(_TEXT_BEFORE_CODE_BLOCKS, code_before_text=False)
    by_id = {c["clause_id"]: c for c in clauses}
    assert by_id["2-5"]["parent_clause_id"] is None
    assert by_id["2-5"]["text_en"] == "Networks Security Management"


def test_text_before_code_objective_and_controls_never_stored_or_leaked():
    clauses = parse_ecc_clauses(_TEXT_BEFORE_CODE_BLOCKS, code_before_text=False)
    ids = {c["clause_id"] for c in clauses}
    assert "Objective" not in ids
    assert "Controls" not in ids
    by_id = {c["clause_id"]: c for c in clauses}
    assert "protection of organization" not in by_id["2-5-1"]["text_en"]


def test_text_before_code_merged_parent_intro_is_recovered_via_colon_split():
    # "2-5-3"'s own intro text lands attributed to its first child
    # ("2-5-3-1") with nothing but the colon to tell them apart —
    # _recover_dropped_parent_intros() splits it back apart: the parent
    # gets its real intro, the first child keeps only its own text, and
    # both children link to the now-real parent.
    clauses = parse_ecc_clauses(_TEXT_BEFORE_CODE_BLOCKS, code_before_text=False)
    by_id = {c["clause_id"]: c for c in clauses}
    assert "2-5-3" in by_id
    assert by_id["2-5-3"]["text_en"] == (
        "The cybersecurity requirements for network security management must include at least the following:"
    )
    assert by_id["2-5-3"]["parent_clause_id"] == "2-5"
    assert by_id["2-5-3-1"]["parent_clause_id"] == "2-5-3"
    assert by_id["2-5-3-1"]["text_en"] == (
        "Logical or physical segregation and segmentation of network segments using firewalls and defense-in-depth principles."
    )
    assert "must include at least the following" not in by_id["2-5-3-1"]["text_en"]
    assert by_id["2-5-3-2"]["parent_clause_id"] == "2-5-3"


def test_text_before_code_recovery_skips_when_no_colon_lead_in_exists():
    # A merged parent ("9-2") whose swallowed text has NO colon-terminated
    # lead-in must stay dropped entirely, not have some arbitrary prefix
    # guessed and split off the first child.
    blocks = [
        {"page": 1, "text": "Some prior sibling text.\n9-1\n"},
        {"page": 1, "text": "First sub-item text with no colon anywhere in it at all.\n9-2-1\n"},
        {"page": 1, "text": "Second sub-item text.\n9-2-2\n"},
        {"page": 1, "text": "9-2\n"},  # parent code, arrives last, nothing accumulated for it
        {"page": 1, "text": "Trailing text for the next real clause.\n9-3\n"},
    ]
    clauses = parse_ecc_clauses(blocks, code_before_text=False)
    by_id = {c["clause_id"]: c for c in clauses}
    assert "9-2" not in by_id
    assert by_id["9-2-1"]["text_en"] == "First sub-item text with no colon anywhere in it at all."
    assert by_id["9-2-1"]["parent_clause_id"] is None
    assert by_id["9-2-2"]["parent_clause_id"] is None


def test_text_before_code_sibling_after_merged_group_unaffected():
    clauses = parse_ecc_clauses(_TEXT_BEFORE_CODE_BLOCKS, code_before_text=False)
    by_id = {c["clause_id"]: c for c in clauses}
    assert by_id["2-5-4"]["parent_clause_id"] == "2-5"
    assert "reviewed periodically" in by_id["2-5-4"]["text_en"]


# ── code-before-text (ECC-2:2024) ────────────────────────────────────────

def test_code_before_text_simple_control():
    clauses = parse_ecc_clauses(_CODE_BEFORE_TEXT_BLOCKS, code_before_text=True)
    by_id = {c["clause_id"]: c for c in clauses}
    assert by_id["1-5-1"]["text_en"].startswith("The cybersecurity department of the entity shall identify")
    assert by_id["1-5-1"]["parent_clause_id"] == "1-5"
    assert by_id["1-5-2"]["parent_clause_id"] == "1-5"


def test_code_before_text_inline_objective_does_not_leak_into_domain_row():
    # "Objective To ensure managing..." sits on the SAME line as "1-5"'s
    # own title in the real PDF — the domain row's text must stop at its
    # own title, not swallow the objective sentence that follows it.
    clauses = parse_ecc_clauses(_CODE_BEFORE_TEXT_BLOCKS, code_before_text=True)
    by_id = {c["clause_id"]: c for c in clauses}
    assert by_id["1-5"]["text_en"] == "Cybersecurity Risk Management"
    assert "Objective" not in by_id["1-5"]["text_en"]
    assert "1-5" == by_id["1-5"]["clause_id"]
    ids = {c["clause_id"] for c in clauses}
    assert "Objective" not in ids and "Controls" not in ids


def test_code_before_text_tall_parent_keeps_its_own_intro_text():
    # Opposite of the text-before-code known limitation: here the parent's
    # code arrives BEFORE its content, so a tall/merged row like "1-5-3"
    # correctly keeps its own lead-in sentence instead of losing it to its
    # first child.
    clauses = parse_ecc_clauses(_CODE_BEFORE_TEXT_BLOCKS, code_before_text=True)
    by_id = {c["clause_id"]: c for c in clauses}
    assert by_id["1-5-3"]["text_en"] == (
        "The cybersecurity risk assessment procedures shall be implemented at least in the "
        "following cases:"
    )


def test_code_before_text_inline_dotted_subcontrols_captured_with_correct_parent():
    clauses = parse_ecc_clauses(_CODE_BEFORE_TEXT_BLOCKS, code_before_text=True)
    by_id = {c["clause_id"]: c for c in clauses}
    for suffix, snippet in [
        ("1", "At early stage of technology projects."),
        ("2", "Before making major changes to technology infrastructure."),
        ("3", "During planning to obtain third party services."),
        ("4", "During planning and before the release of new technology services and products."),
    ]:
        clause_id = f"1.5.3.{suffix}"
        assert by_id[clause_id]["text_en"] == snippet
        assert by_id[clause_id]["parent_clause_id"] == "1-5-3"


def test_code_before_text_next_sibling_after_merged_group_unaffected():
    clauses = parse_ecc_clauses(_CODE_BEFORE_TEXT_BLOCKS, code_before_text=True)
    by_id = {c["clause_id"]: c for c in clauses}
    assert by_id["1-5-4"]["parent_clause_id"] == "1-5"
    assert by_id["1-5-4"]["text_en"].endswith("Changes shall be documented and approved.")


def test_code_before_text_bare_objective_on_its_own_line_also_handled():
    # Page 19's "Objective" is a standalone bare line (unlike page 18's
    # inline "Objective To ensure..."), and "1-6"'s title must not bleed
    # into it either way — both forms have to resolve cleanly.
    clauses = parse_ecc_clauses(_CODE_BEFORE_TEXT_BLOCKS, code_before_text=True)
    by_id = {c["clause_id"]: c for c in clauses}
    assert by_id["1-6"]["text_en"] == "Cybersecurity in Information and Technology Project Management"
    assert by_id["1-6-1"]["parent_clause_id"] == "1-6"
    assert by_id["1-6-1"]["text_en"].endswith("requirements for technology projects.")


# ── shared behavior (order-independent of mode) ──────────────────────────

def test_mixed_hyphen_and_dot_separators_resolve_parent_by_numeric_segments():
    # "1.5.3.1" (dots) resolving its parent to "1-5-3" (hyphens) only
    # passes if parent lookup is genuinely segment-tuple based — the two
    # strings share no textual prefix at all.
    clauses = parse_ecc_clauses(_CODE_BEFORE_TEXT_BLOCKS, code_before_text=True)
    by_id = {c["clause_id"]: c for c in clauses}
    assert by_id["1.5.3.1"]["parent_clause_id"] == "1-5-3"


def test_page_numbers_are_captured_and_track_where_text_started():
    clauses = parse_ecc_clauses(_TEXT_BEFORE_CODE_BLOCKS, code_before_text=False)
    by_id = {c["clause_id"]: c for c in clauses}
    assert by_id["2-5-1"]["page_en"] == 21
    assert by_id["2-5-3-2"]["page_en"] == 22  # text started on the block tagged page 22


def test_overview_table_duplicate_deduped_across_separator_styles():
    # Real bug found in ECC-2:2024: the same domain header appears twice —
    # once in the overview table as "1-7" (hyphen), once at its real
    # content as "1.7" (dot) — identical text, different separator style.
    # A string-keyed dedup lets both through as separate rows (which then
    # broke diff.py's exact-ID alignment downstream); dedup must key on
    # normalized segments so this collapses to one row regardless of which
    # style either occurrence happens to use.
    blocks = [
        {"page": 14, "text": "Compliance with Cybersecurity Standards, Laws and Regulations\n1-7\n"},  # overview table
        {"page": 19, "text": "Compliance with Cybersecurity Standards, Laws and Regulations\n1.7\n"},  # real content, dotted
    ]
    clauses = parse_ecc_clauses(blocks, code_before_text=False)
    assert len(clauses) == 1
    assert clauses[0]["text_en"] == "Compliance with Cybersecurity Standards, Laws and Regulations"


def test_inline_numbers_inside_a_prose_line_never_split():
    blocks = [{"page": 1, "text": "This uses TLS 1.2 or higher and covers 24-7 monitoring windows.\n2-1-1\nReal control text.\n2-1-2\n"}]
    clauses = parse_ecc_clauses(blocks, code_before_text=False)
    by_id = {c["clause_id"]: c for c in clauses}
    assert set(by_id) == {"2-1-1", "2-1-2"}
    assert "TLS 1.2" in by_id["2-1-1"]["text_en"]
    assert by_id["2-1-2"]["text_en"] == "Real control text."


def test_overview_table_duplicate_loses_to_the_fuller_real_entry():
    blocks = [
        {"page": 12, "text": "Cybersecurity Strategy\n1-1\n"},  # overview table: short title only
        {"page": 20, "text": "To establish a clear direction driven by strategic objectives.\n1-1\n"},  # real section, later
    ]
    clauses = parse_ecc_clauses(blocks, code_before_text=False)
    assert len(clauses) == 1  # not 2 — the short duplicate was dropped, not kept alongside
    assert clauses[0]["text_en"] == "To establish a clear direction driven by strategic objectives."
