"""Unit tests for app/adapters/org/.

No database and no network anywhere in this file: adapters produce specs,
and ``persist_org_graph`` (tested separately, and verified against the live
Postgres by hand — see docs/PLAN.md's M4 entry) is what writes them.

The Odoo tests mock ``httpx.Client.post`` rather than the adapter's own
``_call()``, so the actual JSON-RPC envelope this code puts on the wire is
what gets asserted on. Mocking one layer higher would have let the
``method: "call"`` vs ``params.method`` confusion the module docstring
warns about slip straight through.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.adapters.org import (
    ORG_NODE_TYPES,
    CsvAssessmentSheetAdapter,
    OdooAdapter,
    OracleFusionAdapter,
    OrgEdgeSpec,
    OrgGraphFragment,
    OrgNodeSpec,
    SapODataAdapter,
    validate_fragment,
)
from app.adapters.org.odoo import OdooError

FIXTURES = Path(__file__).parent.parent / "fixtures"


# ── validate_fragment ─────────────────────────────────────────────────────

def test_validate_fragment_accepts_a_well_formed_fragment():
    fragment = OrgGraphFragment(
        nodes=[
            OrgNodeSpec("a", "control_mapping", "ECC 2-5-3", {"control_id": "2-5-3"}),
            OrgNodeSpec("b", "process", "Ops"),
        ],
        edges=[OrgEdgeSpec("a", "b", "applies_to")],
    )
    validate_fragment(fragment, source="test")  # must not raise


def test_validate_fragment_rejects_unknown_node_type():
    fragment = OrgGraphFragment(nodes=[OrgNodeSpec("a", "department", "Legal")])
    with pytest.raises(ValueError, match="unknown type"):
        validate_fragment(fragment, source="test")


def test_validate_fragment_rejects_control_mapping_without_control_id():
    # The whole impact engine keys off attrs_json["control_id"]; a
    # control_mapping without one can never be reached by any change, so
    # storing it would be storing a node that silently does nothing.
    fragment = OrgGraphFragment(nodes=[OrgNodeSpec("a", "control_mapping", "ECC ???")])
    with pytest.raises(ValueError, match="control_id"):
        validate_fragment(fragment, source="test")


def test_validate_fragment_rejects_unknown_relation():
    fragment = OrgGraphFragment(
        nodes=[OrgNodeSpec("a", "policy", "P"), OrgNodeSpec("b", "process", "Q")],
        edges=[OrgEdgeSpec("a", "b", "vaguely_relates_to")],
    )
    with pytest.raises(ValueError, match="unknown relation"):
        validate_fragment(fragment, source="test")


def test_validate_fragment_rejects_edge_to_a_nonexistent_node():
    fragment = OrgGraphFragment(
        nodes=[OrgNodeSpec("a", "policy", "P")],
        edges=[OrgEdgeSpec("a", "ghost", "governs")],
    )
    with pytest.raises(ValueError, match="unknown node key"):
        validate_fragment(fragment, source="test")


def test_validate_fragment_rejects_duplicate_keys():
    fragment = OrgGraphFragment(
        nodes=[OrgNodeSpec("a", "policy", "P"), OrgNodeSpec("a", "process", "Q")],
    )
    with pytest.raises(ValueError, match="duplicate node key"):
        validate_fragment(fragment, source="test")


# ── CsvAssessmentSheetAdapter ─────────────────────────────────────────────

def test_csv_resolves_real_world_header_names():
    # None of these are the literal field names in the takeoff prompt;
    # every one of them is a plausible column title in a real workbook.
    columns = CsvAssessmentSheetAdapter.resolve_columns(
        ["Control Reference Number", "Compliance Level", "Responsible Party", "Evidence Reference", "Notes"]
    )
    assert columns["control_id"] == "Control Reference Number"
    assert columns["status"] == "Compliance Level"
    assert columns["owner"] == "Responsible Party"
    assert columns["evidence_ref"] == "Evidence Reference"


def test_csv_resolves_arabic_header_names():
    columns = CsvAssessmentSheetAdapter.resolve_columns(["رقم الضابط", "حالة الالتزام", "الجهة المسؤولة", "الدليل"])
    assert columns["control_id"] == "رقم الضابط"
    assert columns["status"] == "حالة الالتزام"
    assert columns["owner"] == "الجهة المسؤولة"


def test_csv_missing_control_column_fails_loudly_and_shows_the_headers():
    with pytest.raises(ValueError) as excinfo:
        CsvAssessmentSheetAdapter.resolve_columns(["Widget", "Gadget"])
    assert "Widget" in str(excinfo.value)  # tell the user what WAS there, not just what wasn't


def test_csv_optional_columns_may_be_absent():
    columns = CsvAssessmentSheetAdapter.resolve_columns(["control_id"])
    assert columns == {"control_id": "control_id"}


@pytest.mark.parametrize("raw,expected", [
    ("Compliant", "compliant"),
    ("Partially Compliant", "partially_compliant"),
    ("Not Compliant", "not_compliant"),
    ("Not Applicable", "not_applicable"),
    ("ملتزم جزئيا", "partially_compliant"),
    ("Somewhat, probably", "unknown"),  # unrecognized must NOT be forced into a bucket
])
def test_csv_status_normalization(raw, expected):
    assert CsvAssessmentSheetAdapter.normalize_status(raw) == expected


def test_csv_fixture_produces_the_expected_graph():
    adapter = CsvAssessmentSheetAdapter(FIXTURES / "sample_assessment.csv", strict=False)
    fragment = adapter.fetch()
    validate_fragment(fragment, source="csv")

    by_type: dict[str, list[OrgNodeSpec]] = {}
    for node in fragment.nodes:
        by_type.setdefault(node.type, []).append(node)

    controls = {n.attrs["control_id"] for n in by_type["control_mapping"]}
    assert controls == {"2-5-3", "2-5-3-1", "2-8-3-1", "2-11-3", "2-2-3", "4-1-3"}

    # Owners and evidence are deduplicated across rows, not repeated per control.
    assert len(by_type["owner"]) == 3          # OT Engineering, CISO Office, Procurement
    assert len(by_type["evidence"]) == 3       # EV-NET-004, EV-PT-2025, EV-AC-2026-H1

    # Rows with no evidence reference must not invent an evidence node.
    not_applicable = next(n for n in by_type["control_mapping"] if n.attrs["control_id"] == "4-1-3")
    assert not_applicable.attrs["status"] == "not_applicable"
    assert not any(e.from_key == not_applicable.key and e.relation == "evidenced_by" for e in fragment.edges)

    relations = {e.relation for e in fragment.edges}
    assert relations == {"owned_by", "evidenced_by"}


def test_csv_preserves_the_raw_status_alongside_the_normalized_one():
    adapter = CsvAssessmentSheetAdapter(FIXTURES / "sample_assessment.csv", strict=False)
    fragment = adapter.fetch()
    node = next(n for n in fragment.nodes
                if n.type == "control_mapping" and n.attrs["control_id"] == "2-2-3")
    assert node.attrs["status"] == "partially_compliant"
    assert node.attrs["status_raw"] == "ملتزم جزئيا"  # never lose what the sheet actually said


def test_csv_non_strict_skips_heading_and_duplicate_rows_but_records_them():
    adapter = CsvAssessmentSheetAdapter(FIXTURES / "sample_assessment.csv", strict=False)
    adapter.fetch()
    skipped = {value for _, value in adapter.skipped_rows}
    assert "Main Domain 2" in skipped
    assert "2-5-3 (duplicate)" in skipped


def test_csv_strict_mode_refuses_a_non_control_code():
    adapter = CsvAssessmentSheetAdapter(FIXTURES / "sample_assessment.csv", strict=True)
    with pytest.raises(ValueError, match="not an ECC control code"):
        adapter.fetch()


def test_csv_missing_file_names_the_path():
    adapter = CsvAssessmentSheetAdapter(FIXTURES / "does_not_exist.csv")
    with pytest.raises(FileNotFoundError, match="does_not_exist.csv"):
        adapter.fetch()


# ── OdooAdapter ───────────────────────────────────────────────────────────

def _odoo_response(result):
    response = MagicMock()
    response.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": result}
    response.raise_for_status.return_value = None
    return response


def _odoo_error_response(message="Access Denied"):
    response = MagicMock()
    response.json.return_value = {
        "jsonrpc": "2.0", "id": 1,
        "error": {"code": 200, "message": "Odoo Server Error", "data": {"message": message}},
    }
    response.raise_for_status.return_value = None  # Odoo reports errors with HTTP 200
    return response


CATEGORIES = [
    {"id": 7, "name": "Avionics", "complete_name": "Defense / Avionics", "parent_id": [3, "Defense"]},
    {"id": 3, "name": "Defense", "complete_name": "Defense", "parent_id": False},
]
PRODUCTS = [
    {"id": 41, "name": "Flight Controller FC-9", "default_code": "FC-9", "categ_id": [7, "Defense / Avionics"],
     "type": "product", "active": True},
    {"id": 42, "name": "Uncategorized Widget", "default_code": False, "categ_id": [99, "Elsewhere"],
     "type": "consu", "active": True},
]
PARTNERS = [
    {"id": 12, "name": "Najm Microelectronics", "ref": "SUP-012", "country_id": [188, "Saudi Arabia"],
     "supplier_rank": 3, "email": "sales@najm.example"},
]
SUPPLIERINFO = [
    {"id": 1, "partner_id": [12, "Najm Microelectronics"], "product_tmpl_id": [41, "Flight Controller FC-9"]},
    {"id": 2, "partner_id": [12, "Najm Microelectronics"], "product_tmpl_id": [41, "Flight Controller FC-9"]},
    {"id": 3, "partner_id": [99, "Unknown Vendor"], "product_tmpl_id": [41, "Flight Controller FC-9"]},
]


def test_odoo_builds_a_correct_jsonrpc_envelope():
    adapter = OdooAdapter("http://odoo.example:8069/", "demo", "admin", "secret")
    payload = adapter.build_payload("object", "execute_kw", ["demo", 2, "secret", "res.partner", "search_read"])
    # The outer method is ALWAYS "call"; the real method lives under params.
    assert payload["method"] == "call"
    assert payload["jsonrpc"] == "2.0"
    assert payload["params"]["service"] == "object"
    assert payload["params"]["method"] == "execute_kw"
    assert payload["id"] == 1
    assert adapter.build_payload("common", "login", [])["id"] == 2  # ids increment


def test_odoo_fetch_issues_the_expected_calls_in_order():
    adapter = OdooAdapter("http://odoo.example:8069", "demo", "admin@x.example", "secret", limit=250)
    responses = [
        _odoo_response(2),           # login -> uid
        _odoo_response(CATEGORIES),
        _odoo_response(PRODUCTS),
        _odoo_response(PARTNERS),
        _odoo_response(SUPPLIERINFO),
    ]
    with patch.object(httpx.Client, "post", side_effect=responses) as post:
        adapter.fetch()

    assert post.call_count == 5
    urls = {call.args[0] for call in post.call_args_list}
    assert urls == {"http://odoo.example:8069/jsonrpc"}  # trailing slash stripped, one endpoint

    login = post.call_args_list[0].kwargs["json"]["params"]
    assert login == {"service": "common", "method": "login", "args": ["demo", "admin@x.example", "secret"]}

    products = post.call_args_list[2].kwargs["json"]["params"]
    assert products["service"] == "object"
    assert products["method"] == "execute_kw"
    db, uid, password, model, method, args, kwargs = products["args"]
    assert (db, uid, password, model, method) == ("demo", 2, "secret", "product.template", "search_read")
    assert args == [[["active", "=", True]]]
    assert kwargs["limit"] == 250
    assert "categ_id" in kwargs["fields"]

    partners = post.call_args_list[3].kwargs["json"]["params"]["args"]
    assert partners[5] == [[["supplier_rank", ">", 0]]]  # suppliers only, not every contact


def test_odoo_every_call_is_read_only():
    adapter = OdooAdapter("http://odoo.example:8069", "demo", "admin", "secret")
    responses = [_odoo_response(2), _odoo_response([]), _odoo_response([]), _odoo_response([]), _odoo_response([])]
    with patch.object(httpx.Client, "post", side_effect=responses) as post:
        adapter.fetch()
    for call in post.call_args_list[1:]:
        # args[4] of an execute_kw payload is the model method being invoked
        assert call.kwargs["json"]["params"]["args"][4] == "search_read"


def test_odoo_raises_on_an_error_body_despite_http_200():
    # The failure mode this guards: Odoo answers 200 OK with an "error"
    # key, so raise_for_status() passes and the adapter would otherwise
    # return an empty graph that looks like "this tenant has no data".
    adapter = OdooAdapter("http://odoo.example:8069", "demo", "admin", "wrong")
    with patch.object(httpx.Client, "post", return_value=_odoo_error_response("Access Denied")):
        with pytest.raises(OdooError, match="Access Denied"):
            adapter.fetch()


def test_odoo_raises_when_login_returns_false():
    # Bad credentials give result=False, not an error object.
    adapter = OdooAdapter("http://odoo.example:8069", "demo", "admin", "wrong")
    with patch.object(httpx.Client, "post", return_value=_odoo_response(False)):
        with pytest.raises(OdooError, match="login failed"):
            adapter.fetch()


def test_odoo_maps_records_to_nodes_and_edges():
    adapter = OdooAdapter("http://odoo.example:8069", "demo", "admin", "secret")
    fragment = adapter.to_fragment(CATEGORIES, PRODUCTS, PARTNERS, SUPPLIERINFO)
    validate_fragment(fragment, source="odoo")

    by_key = {n.key: n for n in fragment.nodes}
    assert set(by_key) == {
        "odoo_category_7", "odoo_category_3",
        "odoo_product_41", "odoo_product_42",
        "odoo_supplier_12",
    }
    # Categories become product nodes flagged as lines — see odoo.py's
    # docstring for why the node vocabulary was not widened for them.
    assert by_key["odoo_category_7"].type == "product"
    assert by_key["odoo_category_7"].attrs["is_product_line"] is True
    assert by_key["odoo_product_41"].attrs["is_product_line"] is False
    assert by_key["odoo_product_41"].attrs["sku"] == "FC-9"
    assert by_key["odoo_supplier_12"].type == "supplier"
    assert by_key["odoo_supplier_12"].attrs["country"] == "Saudi Arabia"

    edges = {(e.from_key, e.to_key, e.relation) for e in fragment.edges}
    assert ("odoo_category_7", "odoo_category_3", "belongs_to_line") in edges
    assert ("odoo_product_41", "odoo_category_7", "belongs_to_line") in edges
    assert ("odoo_supplier_12", "odoo_product_41", "supplies") in edges


def test_odoo_never_emits_a_dangling_edge_for_an_out_of_window_reference():
    # product 42's category (99) and supplierinfo row 3's partner (99) were
    # never pulled. Emitting edges to them would produce a fragment that
    # fails validate_fragment() at load time; skipping them is what keeps a
    # limit-truncated pull usable.
    adapter = OdooAdapter("http://odoo.example:8069", "demo", "admin", "secret")
    fragment = adapter.to_fragment(CATEGORIES, PRODUCTS, PARTNERS, SUPPLIERINFO)
    keys = {n.key for n in fragment.nodes}
    for edge in fragment.edges:
        assert edge.from_key in keys and edge.to_key in keys
    assert not any(e.from_key == "odoo_product_42" for e in fragment.edges)


def test_odoo_collapses_duplicate_supplierinfo_lines():
    # supplierinfo allows several price lines per supplier/product pair;
    # each must not become its own edge.
    adapter = OdooAdapter("http://odoo.example:8069", "demo", "admin", "secret")
    fragment = adapter.to_fragment(CATEGORIES, PRODUCTS, PARTNERS, SUPPLIERINFO)
    supplies = [e for e in fragment.edges if e.relation == "supplies"]
    assert len(supplies) == 1


def test_odoo_can_skip_the_supplier_link_pull():
    adapter = OdooAdapter("http://odoo.example:8069", "demo", "admin", "secret",
                          include_supplier_links=False)
    responses = [_odoo_response(2), _odoo_response([]), _odoo_response([]), _odoo_response([])]
    with patch.object(httpx.Client, "post", side_effect=responses) as post:
        adapter.fetch()
    assert post.call_count == 4  # login + 3 models, no product.supplierinfo


# ── Stubs ─────────────────────────────────────────────────────────────────

def test_sap_stub_raises_rather_than_returning_an_empty_graph():
    with pytest.raises(NotImplementedError) as excinfo:
        SapODataAdapter(api_key="x").fetch()
    message = str(excinfo.value)
    assert "sandbox.api.sap.com" in message
    assert "ERP_INTEGRATION_GUIDE" in message


def test_oracle_stub_raises_and_explains_it_is_blocked_not_merely_unwritten():
    with pytest.raises(NotImplementedError) as excinfo:
        OracleFusionAdapter().fetch()
    message = str(excinfo.value)
    assert "no public sandbox" in message
    assert "ERP_INTEGRATION_GUIDE" in message


def test_oracle_base_url_requires_both_per_tenant_parts():
    with pytest.raises(ValueError, match="tenant and a datacenter"):
        OracleFusionAdapter(tenant="acme").base_url()
    assert OracleFusionAdapter(tenant="acme", datacenter="us2").base_url() == (
        "https://acme.fa.us2.oraclecloud.com/fscmRestApi/resources/11.13.18.05"
    )


def test_every_adapter_declares_a_distinct_name():
    names = {
        CsvAssessmentSheetAdapter.name,
        OdooAdapter.name,
        SapODataAdapter.name,
        OracleFusionAdapter.name,
    }
    assert len(names) == 4


def test_node_type_vocabulary_matches_the_takeoff_prompt():
    assert ORG_NODE_TYPES == {
        "product", "process", "policy", "control_mapping",
        "evidence", "owner", "supplier", "site",
    }
