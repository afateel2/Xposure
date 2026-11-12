"""
Company workspace tests: the sandboxed versioned store, the executor with a
mocked LLM, the /company routes, and the approve/undo wiring in
routes/actions.py.

Same discipline as test_routes.py: a real SQLAlchemy session on in-memory
SQLite, real files in a pytest tmp dir (COMPANY_DIR override, so the real
working copy is never touched), and only the model call itself mocked
(`executor._call_llm`), since a mock of the store or executor would just
agree with whatever the code did.
"""

import re
from datetime import date
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import require_user
from app.company import executor, nodes as company_nodes, store
from app.config import settings
from app.db.base import Base
from app.db.models import Action, AuditLog, Change, Clause, Impact, OrgEdge, OrgNode, Regulation, RegulationVersion, Regulator
from app.db.session import get_db
from app.main import app

from .auth_fixtures import TEST_USER

EM_DASH = "\u2014"
NETWORK_PROC = "procedures/network-security-procedure.md"
SCADA_CONFIG = "systems/scada-lite-config.yaml"
TODAY = date.today().isoformat()


# Fixtures

@pytest.fixture
def company(tmp_path, monkeypatch):
    """A throwaway working copy created from the real baseline, with its own LLM cache dir."""
    monkeypatch.setattr(settings, "company_dir", str(tmp_path / "company"))
    monkeypatch.setattr(settings, "company_cache_dir", str(tmp_path / "cache"))
    store.ensure_company()
    return tmp_path / "company"


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def client(db):
    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    app.dependency_overrides[require_user] = lambda: TEST_USER
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_user, None)


def _seed(db, *, node_type="policy", node_attrs=None, action_type="update_procedure", node_name="Network Security Procedure"):
    regulator = Regulator(code="nca", name_ar="الهيئة", name_en="National Cybersecurity Authority", weight=1.0)
    db.add(regulator)
    db.flush()
    regulation = Regulation(regulator_id=regulator.id, code="ecc", title_ar="الضوابط", title_en="Essential Cybersecurity Controls")
    db.add(regulation)
    db.flush()
    v1 = RegulationVersion(regulation_id=regulation.id, version_label="1-2018", file_sha256="a", source_url="")
    v2 = RegulationVersion(regulation_id=regulation.id, version_label="2-2024", file_sha256="b", source_url="")
    db.add_all([v1, v2])
    db.flush()
    db.add(Clause(version_id=v2.id, clause_id="2-5-3-9", text_en="Protecting against Distributed Denial of Service (DDoS) attacks to limit risks arising from these attacks.", order_index=0))
    change = Change(
        regulation_id=regulation.id, from_version_id=v1.id, to_version_id=v2.id,
        old_clause_id=None, new_clause_id="2-5-3-9", match_kind="added", change_type="new_obligation",
        material=True, confidence=0.9, summary_en="A new requirement protects against DDoS attacks.", summary_ar="متطلب جديد.",
        diff_spans_json={"ops": []},
    )
    db.add(change)
    db.flush()
    attrs = {"file": NETWORK_PROC} if node_attrs is None else node_attrs
    node = OrgNode(type=node_type, name=node_name, attrs_json=attrs)
    db.add(node)
    db.flush()
    impact = Impact(
        change_id=change.id, node_id=node.id, path_json={"scope_match": "ancestor", "depth": 1, "summary": node.name},
        note_en="The procedure must add DDoS protection.", note_ar="ن", recommended_actions_json=[action_type],
    )
    db.add(impact)
    db.flush()
    action = Action(
        change_id=change.id, type=action_type, level="draft_then_approve", status="pending",
        payload_json={"impact_id": impact.id, "impact_node_id": node.id},
    )
    db.add(action)
    db.commit()
    return {"change_id": change.id, "node_id": node.id, "impact_id": impact.id, "action_id": action.id}


class FakeLLM:
    """Stands in for executor._call_llm. `mode` picks the behavior; `calls` records prompts."""

    def __init__(self, mode="good"):
        self.mode = mode
        self.calls: list[list[dict]] = []

    @staticmethod
    def current_file(messages) -> str:
        user = messages[1]["content"]
        return re.search(r"<current_file>\n(.*?)\n</current_file>", user, re.DOTALL).group(1) + "\n"

    def __call__(self, messages):
        self.calls.append(messages)
        current = self.current_file(messages)
        if self.mode == "empty_edit":
            return current
        if self.mode == "drop_half":
            lines = current.splitlines()
            return "\n".join(lines[: len(lines) // 2]) + "\n"
        if self.mode == "yaml_drop_key":
            return current.replace("firewall_default_action: deny\n", "")
        if self.mode == "em_dash":
            return self._edit(current).replace("DDoS attacks", f"DDoS attacks {EM_DASH} that disrupt production")
        return self._edit(current)

    @staticmethod
    def _edit(current: str) -> str:
        if "version:" in current.splitlines()[0]:  # YAML settings file
            text = current.replace("network:\n", "network:\n  ddos_protection:\n    enabled: true\n", 1)
            return text.replace('version: "1.0"', 'version: "9.9"', 1)
        section = (
            "## 10. DDoS protection\n\n"
            "- The company protects internet-facing services against Distributed Denial of Service (DDoS) attacks.\n"
            "- DDoS protection is reviewed every six months together with the firewall rules.\n\n"
        )
        text = current.replace("## Change log", section + "## Change log", 1)
        text = text.replace("- Version: 1.0", "- Version: 9.9", 1)  # wrong on purpose: code must own the version
        return text.rstrip("\n") + "\n- 9.9 (2020-01-01): Added DDoS protection for ECC-2:2024 2-5-3-9.\n"


@pytest.fixture
def fake_llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(executor, "_call_llm", fake)
    return fake


# Baseline content

def test_baseline_files_are_well_formed_and_free_of_em_dashes():
    base = store.baseline_dir()
    files = [p for p in base.rglob("*") if p.is_file()]
    assert len(files) >= 9
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert EM_DASH not in text, path
        assert path.suffix in (".md", ".yaml"), path
        if path.name != "profile.yaml":
            assert store.doc_version(text) == "1.0", path
            assert store.doc_last_reviewed(text), path
        if path.suffix == ".yaml":
            assert isinstance(yaml.safe_load(text), dict), path


def test_profile_names_the_company_and_the_applied_regulation(company):
    profile = store.load_profile()
    assert profile["name_en"] == "Eastern Industrial Company"
    assert profile["applied_regulation"] == "ECC-1:2018"
    assert isinstance(profile["employees"], int)
    assert len(profile["products"]) == 2


def test_org_seed_file_attributes_point_at_real_baseline_files():
    from app.impact import DEFAULT_ORG_FILE, parse_org_yaml

    fragment = parse_org_yaml(DEFAULT_ORG_FILE)
    mapped = 0
    for node in fragment.nodes:
        for attr in ("file", "config_file"):
            rel = node.attrs.get(attr)
            if rel:
                mapped += 1
                assert (store.baseline_dir() / rel).is_file(), f"{node.key}.{attr} -> {rel}"
    assert mapped >= 8
    owners = [n for n in fragment.nodes if n.type == "owner"]
    assert all(o.attrs.get("email") and o.attrs.get("role") for o in owners)
    text = DEFAULT_ORG_FILE.read_text(encoding="utf-8")
    for old_name in ("Saqr", "Hazm", "Tactical UAV", "Wathiq", EM_DASH):
        assert old_name not in text


# Store: path safety

@pytest.mark.parametrize("bad", [
    "../outside.md", "policies/../../outside.md", "..\\outside.md", "/etc/passwd.md", "C:/Windows/x.md", "C:\\x.md",
    "policies//x.md", "./policies/x.md", "policies/x.txt", "policies/x", ".history/policies/x.md", "policies/.hidden.md",
    "", "   ", "policies/x.md\x00.txt", "policies/x.md:stream", "policies/x.md.", "policies/*.md",
])
def test_resolve_path_rejects_unsafe_paths(company, bad):
    with pytest.raises(store.UnsafePathError):
        store.resolve_path(bad)


def test_resolve_path_accepts_a_normal_document_and_normalizes_backslashes(company):
    rel, target = store.resolve_path("policies\\information-security-policy.md")
    assert rel == "policies/information-security-policy.md"
    assert target.is_relative_to(company.resolve())


def test_read_and_write_refuse_traversal_and_unknown_files(company):
    with pytest.raises(store.UnsafePathError):
        store.read_file("../../secret.md")
    with pytest.raises(store.UnsafePathError):
        store.write_new_version("../evil.md", "# x\n", origin="agent")
    with pytest.raises(store.FileNotInCompanyError):
        store.write_new_version("policies/brand-new.md", "# x\n", origin="agent")
    assert not (company.parent / "evil.md").exists()


def test_write_validates_content(company):
    with pytest.raises(store.InvalidContentError):
        store.write_new_version(NETWORK_PROC, "   \n", origin="agent")
    with pytest.raises(store.InvalidContentError):
        store.write_new_version(NETWORK_PROC, "x" * (store.MAX_FILE_BYTES + 1), origin="agent")
    with pytest.raises(store.InvalidContentError):
        store.write_new_version(SCADA_CONFIG, "- just\n- a list\n", origin="agent")
    with pytest.raises(store.InvalidContentError):
        store.write_new_version(SCADA_CONFIG, "a: [unclosed\n", origin="agent")
    assert len(store.get_versions(NETWORK_PROC)) == 1


# Store: versions, revert, reset

def test_versions_are_append_only_and_revert_restores_content_as_a_new_version(company):
    original = store.read_file(NETWORK_PROC)
    assert [v["origin"] for v in store.get_versions(NETWORK_PROC)] == ["baseline"]

    entry = store.write_new_version(NETWORK_PROC, original.replace("Version: 1.0", "Version: 1.1"), origin="agent", action_id=7)
    assert (entry["n"], entry["doc_version"], entry["action_id"]) == (2, "1.1", 7)
    assert "Version: 1.1" in store.read_file(NETWORK_PROC)

    reverted = store.revert_to_previous(NETWORK_PROC)
    assert (reverted["n"], reverted["origin"], reverted["reverted_to"]) == (3, "revert", 1)
    assert store.read_file(NETWORK_PROC) == original

    versions = store.get_versions(NETWORK_PROC)
    assert [v["n"] for v in versions] == [1, 2, 3]
    assert "Version: 1.1" in store.read_version(NETWORK_PROC, 2)  # history keeps the reverted version
    assert (company / ".history" / "procedures" / "network-security-procedure.md" / "v0002.md").is_file()

    info = store.file_info(NETWORK_PROC)
    assert (info["version_count"], info["last_origin"], info["agent_edited"]) == (3, "revert", False)


def test_revert_with_a_single_version_is_refused(company):
    with pytest.raises(store.NothingToRevertError):
        store.revert_to_previous(NETWORK_PROC)


def test_reset_company_restores_baseline_and_history(company):
    original = store.read_file(NETWORK_PROC)
    store.write_new_version(NETWORK_PROC, original + "\n- extra line\n", origin="agent")
    result = store.reset_company()
    assert result["files"] >= 8
    assert store.read_file(NETWORK_PROC) == original
    assert len(store.get_versions(NETWORK_PROC)) == 1


def test_reset_company_refuses_a_directory_that_is_not_a_working_copy(tmp_path, monkeypatch):
    stray = tmp_path / "some" / "other" / "dir"
    stray.mkdir(parents=True)
    (stray / "important.txt").write_text("keep me", encoding="utf-8")
    monkeypatch.setattr(settings, "company_dir", str(stray))
    with pytest.raises(store.CompanyStoreError):
        store.reset_company()
    assert (stray / "important.txt").read_text(encoding="utf-8") == "keep me"


def test_reset_company_refuses_to_use_the_baseline_as_the_working_copy(monkeypatch):
    monkeypatch.setattr(settings, "company_dir", str(store.baseline_dir()))
    with pytest.raises(store.CompanyStoreError):
        store.reset_company()


def test_bump_version():
    assert store.bump_version("1.0") == "1.1"
    assert store.bump_version("1.9") == "1.10"
    assert store.bump_version("2") == "2.1"
    assert store.bump_version(None) == "1.1"


# Executor

def test_executor_edits_the_mapped_document_with_a_correct_diff(db, company, fake_llm):
    ids = _seed(db)
    action = db.get(Action, ids["action_id"])
    before = store.read_file(NETWORK_PROC)

    result = executor.execute_action(db, action)
    db.commit()

    assert result.applied, result.reason
    effect = result.effect
    assert effect["kind"] == "file_edit" and effect["path"] == NETWORK_PROC
    assert (effect["version_before"], effect["version_after"]) == ("1.0", "1.1")  # code owns the version, not the model's "9.9"
    assert effect["cached"] is False
    assert effect["added"] > 0 and effect["removed"] >= 1  # the version and reviewed lines changed
    assert "+## 10. DDoS protection" in effect["diff_unified"]
    assert effect["diff_unified"].startswith(f"--- {NETWORK_PROC} (v1.0)")

    after = store.read_file(NETWORK_PROC)
    assert after != before
    assert "- Version: 1.1" in after and "9.9" not in after
    assert f"- Last reviewed: {TODAY}" in after
    assert f"- 1.1 ({TODAY}):" in after  # code normalized the model's change-log line
    assert "DDoS" in after
    # unrelated content untouched
    for line in ("## 4. Segmentation rules", "- Remote access to the corporate network and to OT systems goes only through the VPN gateway in the DMZ."):
        assert line in after

    # the diff counts match an independent recount
    import difflib
    recount = list(difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0))
    plus = sum(1 for line in recount if line.startswith("+") and not line.startswith("+++"))
    minus = sum(1 for line in recount if line.startswith("-") and not line.startswith("---"))
    assert (effect["added"], effect["removed"]) == (plus, minus)

    versions = store.get_versions(NETWORK_PROC)
    assert [(v["n"], v["origin"], v["doc_version"]) for v in versions] == [(1, "baseline", "1.0"), (2, "agent", "1.1")]

    db.expire_all()
    assert db.get(Action, ids["action_id"]).payload_json["effect"]["path"] == NETWORK_PROC
    assert db.get(Action, ids["action_id"]).payload_json["impact_id"] == ids["impact_id"]  # existing payload kept


def test_executor_prompt_carries_the_change_and_no_em_dash(db, company, fake_llm):
    ids = _seed(db)
    executor.execute_action(db, db.get(Action, ids["action_id"]))
    messages = fake_llm.calls[0]
    joined = "\n".join(m["content"] for m in messages)
    assert "2-5-3-9" in joined and "ECC-2:2024" in joined and "ECC-1:2018" in joined
    assert "Distributed Denial of Service" in joined
    assert "A new requirement protects against DDoS attacks." in joined
    assert "Network Security Procedure" in joined
    assert EM_DASH not in joined
    assert "<regulatory_change>" in joined  # untrusted text is fenced


def test_executor_strips_em_dashes_from_model_output(db, company, monkeypatch):
    fake = FakeLLM("em_dash")
    monkeypatch.setattr(executor, "_call_llm", fake)
    ids = _seed(db)
    result = executor.execute_action(db, db.get(Action, ids["action_id"]))
    assert result.applied
    assert EM_DASH not in store.read_file(NETWORK_PROC)


def test_executor_result_is_cached_and_replays_without_calling_the_model(db, company, fake_llm):
    ids = _seed(db)
    action = db.get(Action, ids["action_id"])
    first = executor.execute_action(db, action)
    assert first.applied and len(fake_llm.calls) == 1
    edited = store.read_file(NETWORK_PROC)

    executor.revert_action_effect(db, action)
    db.commit()
    assert store.read_file(NETWORK_PROC) != edited

    second = executor.execute_action(db, action)
    assert second.applied
    assert second.effect["cached"] is True
    assert len(fake_llm.calls) == 1  # no second model call
    assert store.read_file(NETWORK_PROC) == edited  # identical result on replay
    assert any(p.suffix == ".json" for p in (company.parent / "cache").iterdir())


def test_cache_key_ignores_the_date_so_replays_survive_a_new_day(db, company, fake_llm):
    ids = _seed(db)
    action = db.get(Action, ids["action_id"])
    executor.execute_action(db, action)
    executor.revert_action_effect(db, action)
    db.commit()

    class NextDay(date):
        @classmethod
        def today(cls):
            return date(2031, 1, 2)

    import app.company.executor as ex
    original = ex.date
    ex.date = NextDay
    try:
        replay = executor.execute_action(db, action)
    finally:
        ex.date = original
    assert replay.applied and replay.effect["cached"] is True
    assert len(fake_llm.calls) == 1
    assert "- Last reviewed: 2031-01-02" in store.read_file(NETWORK_PROC)


def test_executor_rejects_an_answer_that_drops_content(db, company, monkeypatch):
    fake = FakeLLM("drop_half")
    monkeypatch.setattr(executor, "_call_llm", fake)
    ids = _seed(db)
    before = store.read_file(NETWORK_PROC)
    result = executor.execute_action(db, db.get(Action, ids["action_id"]))
    assert not result.applied and result.reason_code == "model_failed"
    assert "could not produce a valid edit" in result.reason
    assert len(fake.calls) == executor.MAX_ATTEMPTS  # one corrective retry, then give up
    assert "rejected" in fake.calls[1][-1]["content"]
    assert store.read_file(NETWORK_PROC) == before
    assert len(store.get_versions(NETWORK_PROC)) == 1


def test_executor_reports_no_substantive_edit_honestly(db, company, monkeypatch):
    monkeypatch.setattr(executor, "_call_llm", FakeLLM("empty_edit"))
    ids = _seed(db)
    result = executor.execute_action(db, db.get(Action, ids["action_id"]))
    assert not result.applied and result.reason_code == "no_substantive_edit"
    assert "nothing to change" in result.reason


def test_executor_reports_a_model_failure_without_faking_success(db, company, monkeypatch):
    def broken(messages):
        raise ConnectionError("model endpoint unreachable")

    monkeypatch.setattr(executor, "_call_llm", broken)
    ids = _seed(db)
    result = executor.execute_action(db, db.get(Action, ids["action_id"]))
    assert not result.applied and result.reason_code == "model_failed"
    assert "ConnectionError" in result.reason
    assert len(store.get_versions(NETWORK_PROC)) == 1


def test_executor_technical_change_edits_the_yaml_config_and_only_adds_keys(db, company, fake_llm):
    ids = _seed(db, node_type="product", node_attrs={"config_file": SCADA_CONFIG}, action_type="technical_change", node_name="SCADA-Lite Monitoring System")
    before = yaml.safe_load(store.read_file(SCADA_CONFIG))
    result = executor.execute_action(db, db.get(Action, ids["action_id"]))
    assert result.applied, result.reason
    after_text = store.read_file(SCADA_CONFIG)
    after = yaml.safe_load(after_text)
    assert after["network"]["ddos_protection"] == {"enabled": True}
    assert after["version"] == "1.1" and after["last_reviewed"] == TODAY
    assert any(entry["version"] == "1.1" for entry in after["change_log"])
    # every original key survived
    assert not executor._dropped_keys(before, after)
    assert result.effect["version_after"] == "1.1"


def test_executor_rejects_yaml_that_deletes_a_key(db, company, monkeypatch):
    monkeypatch.setattr(executor, "_call_llm", FakeLLM("yaml_drop_key"))
    ids = _seed(db, node_type="product", node_attrs={"config_file": SCADA_CONFIG}, action_type="technical_change")
    result = executor.execute_action(db, db.get(Action, ids["action_id"]))
    assert not result.applied
    assert "deleted existing keys" in result.reason or "no substantive edit" in result.reason or "could not produce" in result.reason
    assert len(store.get_versions(SCADA_CONFIG)) == 1


def test_executor_validation_rejects_invalid_yaml_and_non_mappings():
    context = {"new_regulation": "ECC-2:2024", "clause_ref": "2-5-3-9", "change_type": "new_obligation"}
    old = 'version: "1.0"\nlast_reviewed: "2025-01-01"\na: 1\nchange_log: []\n'
    with pytest.raises(executor.ExecutorError):
        executor.normalize_and_validate(rel="systems/x.yaml", old=old, raw="a: [oops\n", new_version="1.1", today=TODAY, context=context)
    with pytest.raises(executor.ExecutorError):
        executor.normalize_and_validate(rel="systems/x.yaml", old=old, raw="- a\n- b\n", new_version="1.1", today=TODAY, context=context)


def test_executor_strips_code_fences_around_the_answer(db, company, monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(executor, "_call_llm", lambda messages: "```markdown\n" + fake(messages) + "```")
    ids = _seed(db)
    result = executor.execute_action(db, db.get(Action, ids["action_id"]))
    assert result.applied, result.reason
    assert not store.read_file(NETWORK_PROC).startswith("```")


@pytest.mark.parametrize("action_type", ["notify_owner", "collect_evidence", "reassess_control", "request_license_review"])
def test_executor_ignores_unsupported_action_types(db, company, fake_llm, action_type):
    ids = _seed(db, action_type=action_type)
    result = executor.execute_action(db, db.get(Action, ids["action_id"]))
    assert not result.applied and result.reason_code == "unsupported_action_type"
    assert action_type in result.reason
    assert fake_llm.calls == []
    assert len(store.get_versions(NETWORK_PROC)) == 1


def test_executor_ignores_nodes_without_a_mapped_file(db, company, fake_llm):
    ids = _seed(db, node_type="owner", node_attrs={"email": "x@example.test"}, action_type="update_policy", node_name="IT Security Lead")
    result = executor.execute_action(db, db.get(Action, ids["action_id"]))
    assert not result.applied and result.reason_code == "no_mapped_file"
    assert "IT Security Lead" in result.reason
    assert fake_llm.calls == []


def test_executor_refuses_a_node_whose_mapped_path_escapes_the_sandbox(db, company, fake_llm):
    ids = _seed(db, node_attrs={"file": "../../etc/passwd.md"})
    result = executor.execute_action(db, db.get(Action, ids["action_id"]))
    assert not result.applied and result.reason_code == "file_missing"
    assert fake_llm.calls == []


def test_executor_finds_the_node_through_the_impact_when_the_payload_has_no_node_id(db, company, fake_llm):
    ids = _seed(db)
    action = db.get(Action, ids["action_id"])
    action.payload_json = {"impact_id": ids["impact_id"]}
    db.commit()
    assert executor.execute_action(db, action).applied


def test_revert_action_effect_restores_content_and_moves_the_effect(db, company, fake_llm):
    ids = _seed(db)
    action = db.get(Action, ids["action_id"])
    original = store.read_file(NETWORK_PROC)
    executor.execute_action(db, action)
    reverted, note = executor.revert_action_effect(db, action)
    assert note is None and reverted["version_restored"] == "1.0"
    assert store.read_file(NETWORK_PROC) == original
    assert "effect" not in action.payload_json and action.payload_json["effect_reverted"]["path"] == NETWORK_PROC
    assert [v["origin"] for v in store.get_versions(NETWORK_PROC)] == ["baseline", "agent", "revert"]
    assert executor.revert_action_effect(db, action) == (None, None)  # nothing left to revert


def test_revert_action_effect_refuses_to_clobber_a_newer_version(db, company, fake_llm):
    ids = _seed(db)
    action = db.get(Action, ids["action_id"])
    executor.execute_action(db, action)
    store.write_new_version(NETWORK_PROC, store.read_file(NETWORK_PROC) + "\n- a later manual edit\n", origin="agent")
    reverted, note = executor.revert_action_effect(db, action)
    assert reverted is None and "newer versions" in note
    assert "a later manual edit" in store.read_file(NETWORK_PROC)
    assert "effect" in action.payload_json  # still claims the edit, honestly


# Derived node status

def test_node_status_derivation_rules():
    d = company_nodes.derive_status
    assert d(has_live_effect=False, assigned=0, open_count=0) == "up_to_date"
    assert d(has_live_effect=False, assigned=0, open_count=3) == "action_required"
    assert d(has_live_effect=False, assigned=1, open_count=3) == "assigned"
    assert d(has_live_effect=True, assigned=1, open_count=3) == "updated_by_agent"


# Routes

def test_get_company_returns_profile_and_counts(client, db, company):
    _seed(db)
    body = client.get("/company").json()
    assert body["profile"]["name_en"] == "Eastern Industrial Company"
    assert body["applied_regulation"] == "ECC-1:2018"
    assert body["known_regulation_versions"] == ["ECC-1:2018", "ECC-2:2024"]
    assert body["counts"] == {"files": 8, "nodes": 1, "open_actions": 1, "assigned_actions": 0, "agent_edited_files": 0}


def test_get_company_files_lists_every_managed_file(client, company):
    files = client.get("/company/files").json()["files"]
    paths = {f["path"] for f in files}
    assert paths == {
        "policies/information-security-policy.md", "policies/access-control-policy.md", "policies/cryptography-policy.md",
        NETWORK_PROC, "procedures/production-line-control-procedure.md", "evidence/access-review-log.md",
        SCADA_CONFIG, "systems/icu-200-firmware-config.yaml",
    }
    sample = next(f for f in files if f["path"] == NETWORK_PROC)
    assert (sample["kind"], sample["version"], sample["last_origin"], sample["agent_edited"]) == ("procedure", "1.0", "baseline", False)


def test_get_company_file_returns_content_versions_and_diff(client, db, company, fake_llm):
    ids = _seed(db)
    detail = client.get(f"/company/files/{NETWORK_PROC}").json()
    assert detail["content"].startswith("# Network Security Procedure")
    assert detail["diff"] is None  # only one version so far
    assert [v["origin"] for v in detail["versions"]] == ["baseline"]
    assert detail["nodes"] == [{"id": ids["node_id"], "name": "Network Security Procedure", "type": "policy"}]

    client.post(f"/actions/{ids['action_id']}/approve")
    detail = client.get(f"/company/files/{NETWORK_PROC}").json()
    assert [v["origin"] for v in detail["versions"]] == ["baseline", "agent"]
    assert detail["version"] == "1.1" and detail["agent_edited"] is True
    assert detail["diff"]["from_version"] == "1.0" and detail["diff"]["to_version"] == "1.1"
    assert "+## 10. DDoS protection" in detail["diff"]["unified"]
    assert detail["diff"]["added"] > 0

    old = client.get(f"/company/files/{NETWORK_PROC}", params={"version": 1}).json()
    assert "DDoS" not in old["content"] and old["diff"] is None
    assert client.get(f"/company/files/{NETWORK_PROC}", params={"version": 99}).status_code == 404


def test_get_company_file_rejects_traversal_and_unknown_paths(client, company):
    assert client.get("/company/files/policies/nope.md").status_code == 404
    assert client.get("/company/files/policies/x.txt").status_code == 400
    assert client.get("/company/files/%2e%2e/%2e%2e/secret.md").status_code == 400
    assert client.get("/company/files/..%2F..%2Fsecret.md").status_code == 400
    assert client.get("/company/files/.history/procedures/network-security-procedure.md/index.json").status_code == 400
    assert client.post("/company/files/%2e%2e/x.md/revert").status_code == 400


def test_manual_revert_route_restores_previous_version_and_updates_the_action(client, db, company, fake_llm):
    ids = _seed(db)
    original = store.read_file(NETWORK_PROC)
    client.post(f"/actions/{ids['action_id']}/approve")
    assert store.read_file(NETWORK_PROC) != original

    response = client.post(f"/company/files/{NETWORK_PROC}/revert")
    assert response.status_code == 200
    body = response.json()
    assert body["reverted_to_n"] == 1 and body["actions_marked"] == [ids["action_id"]]
    assert [v["origin"] for v in body["versions"]] == ["baseline", "agent", "revert"]
    assert store.read_file(NETWORK_PROC) == original

    db.expire_all()
    payload = db.get(Action, ids["action_id"]).payload_json
    assert "effect" not in payload and payload["effect_reverted"]["reverted_by"] == "file_revert"
    assert db.query(AuditLog).filter(AuditLog.event == "company_file_reverted").count() == 1

    # nothing older to restore on an untouched file
    assert client.post("/company/files/policies/access-control-policy.md/revert").status_code == 409


def _seed_org(db):
    """Two nodes hit by the same change: a policy with a file and an owner without one."""
    ids = _seed(db)
    owner = OrgNode(type="owner", name="IT Security Lead", attrs_json={"email": "it@example.test", "role": "IT Security Lead"})
    db.add(owner)
    db.flush()
    db.add(OrgEdge(from_id=ids["node_id"], to_id=owner.id, relation="owned_by"))
    impact = Impact(change_id=ids["change_id"], node_id=owner.id, path_json={"depth": 1}, note_en="n", note_ar="ن", recommended_actions_json=["update_policy"])
    db.add(impact)
    db.flush()
    owner_action = Action(
        change_id=ids["change_id"], type="update_policy", level="draft_then_approve", status="pending",
        payload_json={"impact_id": impact.id, "impact_node_id": owner.id},
    )
    db.add(owner_action)
    db.commit()
    return {**ids, "owner_id": owner.id, "owner_action_id": owner_action.id}


def test_company_nodes_report_status_owner_and_file_metadata(client, db, company, fake_llm):
    ids = _seed_org(db)
    body = client.get("/company/nodes").json()
    by_id = {n["id"]: n for n in body["nodes"]}
    policy, owner = by_id[ids["node_id"]], by_id[ids["owner_id"]]

    assert policy["status"] == "action_required" and policy["status_label_en"] == "Action required"
    assert policy["status_label_ar"] == "يتطلب إجراءً"
    assert policy["display_type"] == "policy" and policy["path"] == NETWORK_PROC and policy["version"] == "1.0"
    assert policy["owner"] == {"id": ids["owner_id"], "name": "IT Security Lead", "email": "it@example.test", "role": "IT Security Lead"}
    assert policy["open_action_count"] == 1 and policy["change_ids"] == [ids["change_id"]]
    assert owner["owner"] is None and owner["path"] is None and owner["last_modified"] is None
    assert body["counts_by_status"] == {"action_required": 2}

    client.post(f"/actions/{ids['action_id']}/approve")
    client.post(f"/actions/{ids['owner_action_id']}/delegate", json={"assignee_name": "Sara"})
    body = client.get("/company/nodes").json()
    by_id = {n["id"]: n for n in body["nodes"]}
    assert by_id[ids["node_id"]]["status"] == "updated_by_agent"
    assert by_id[ids["node_id"]]["agent_edit_count"] == 1 and by_id[ids["node_id"]]["last_origin"] == "agent"
    assert by_id[ids["node_id"]]["open_action_count"] == 0
    assert by_id[ids["owner_id"]]["status"] == "assigned"
    assert by_id[ids["owner_id"]]["assigned_action_count"] == 1


def test_company_nodes_hide_control_mappings_unless_asked(client, db, company):
    _seed(db)
    db.add(OrgNode(type="control_mapping", name="ECC 2-5-3", attrs_json={"control_id": "2-5-3"}))
    db.commit()
    assert len(client.get("/company/nodes").json()["nodes"]) == 1
    assert len(client.get("/company/nodes", params={"include_controls": True}).json()["nodes"]) == 2


# Approve / undo wiring

def test_approve_runs_the_executor_and_returns_the_effect(client, db, company, fake_llm):
    ids = _seed(db)
    response = client.post(f"/actions/{ids['action_id']}/approve")
    assert response.status_code == 200
    body = response.json()
    assert (body["id"], body["status"]) == (ids["action_id"], "approved")
    effect = body["effect"]
    assert effect["kind"] == "file_edit" and effect["path"] == NETWORK_PROC
    assert (effect["version_before"], effect["version_after"]) == ("1.0", "1.1")
    assert set(effect) >= {"added", "removed", "diff_unified", "executed_at", "cached"}
    assert body["effect_note"] is None

    rows = db.query(AuditLog).filter(AuditLog.ref_id == ids["action_id"]).order_by(AuditLog.id).all()
    assert [r.event for r in rows] == ["action_approved", "webhook_action_approved", "action_effect_applied"]
    applied = rows[2].payload_json
    assert applied["path"] == NETWORK_PROC and applied["version_before"] == "1.0" and applied["version_after"] == "1.1"
    assert applied["added"] == effect["added"] and applied["removed"] == effect["removed"]


def test_change_detail_exposes_the_effect_on_the_action(client, db, company, fake_llm):
    ids = _seed(db)
    action_out = lambda: client.get(f"/changes/{ids['change_id']}").json()["impacts"][0]["actions"][0]  # noqa: E731
    assert action_out()["effect"] is None
    client.post(f"/actions/{ids['action_id']}/approve")
    assert action_out()["effect"]["path"] == NETWORK_PROC
    client.post(f"/actions/{ids['action_id']}/undo")
    assert action_out()["effect"] is None


def test_approve_still_succeeds_when_the_agent_cannot_edit(client, db, company, monkeypatch):
    def broken(messages):
        raise TimeoutError("slow model")

    monkeypatch.setattr(executor, "_call_llm", broken)
    ids = _seed(db)
    response = client.post(f"/actions/{ids['action_id']}/approve")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved" and body["effect"] is None
    assert "could not produce a valid edit" in body["effect_note"]
    assert db.query(AuditLog).filter(AuditLog.event == "action_effect_failed").count() == 1
    assert len(store.get_versions(NETWORK_PROC)) == 1


def test_approve_with_an_unsupported_action_type_is_decision_only(client, db, company, fake_llm):
    ids = _seed(db, action_type="notify_owner")
    body = client.post(f"/actions/{ids['action_id']}/approve").json()
    assert body["status"] == "approved" and body["effect"] is None
    assert "notify_owner" in body["effect_note"]
    assert fake_llm.calls == []
    assert db.query(AuditLog).filter(AuditLog.event.like("action_effect%")).count() == 0


def test_bulk_approve_stays_decision_only(client, db, company, fake_llm):
    ids = _seed(db)
    response = client.post("/actions/bulk", json={"action_ids": [ids["action_id"]], "decision": "approve"})
    assert response.status_code == 200 and response.json()["updated"] == [ids["action_id"]]
    assert fake_llm.calls == []
    assert len(store.get_versions(NETWORK_PROC)) == 1
    db.expire_all()
    assert "effect" not in db.get(Action, ids["action_id"]).payload_json


def test_undo_reverts_the_file_and_reports_it_outside_side_effects(client, db, company, fake_llm):
    ids = _seed(db)
    original = store.read_file(NETWORK_PROC)
    client.post(f"/actions/{ids['action_id']}/approve")
    assert store.read_file(NETWORK_PROC) != original

    response = client.post(f"/actions/{ids['action_id']}/undo")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["effect_reverted"]["path"] == NETWORK_PROC and body["effect_reverted"]["version_restored"] == "1.0"
    assert body["effect_reapplied"] is None
    # the webhook stays listed as not reversed only if it was really sent; the file edit is reversible and never listed
    assert not any("policy" in s or NETWORK_PROC in s or "file" in s for s in body["side_effects_not_reversed"])
    assert store.read_file(NETWORK_PROC) == original

    events = [r.event for r in db.query(AuditLog).filter(AuditLog.ref_id == ids["action_id"]).order_by(AuditLog.id)]
    assert events.count("action_effect_applied") == 1 and events.count("action_effect_reverted") == 1
    assert events[-1] == "action_status_reverted"
    assert [v["origin"] for v in store.get_versions(NETWORK_PROC)] == ["baseline", "agent", "revert"]


def test_redo_applies_the_cached_edit_again_and_undo_again_reverts_it(client, db, company, fake_llm):
    ids = _seed(db)
    approved = client.post(f"/actions/{ids['action_id']}/approve").json()
    edited = store.read_file(NETWORK_PROC)
    client.post(f"/actions/{ids['action_id']}/undo")

    redo = client.post(f"/actions/{ids['action_id']}/undo").json()
    assert redo["status"] == "approved"
    assert redo["effect_reapplied"]["cached"] is True
    assert redo["effect_reapplied"]["version_after"] == approved["effect"]["version_after"]
    assert len(fake_llm.calls) == 1  # the model was not asked again
    assert store.read_file(NETWORK_PROC) == edited

    undo_again = client.post(f"/actions/{ids['action_id']}/undo").json()
    assert undo_again["status"] == "pending" and undo_again["effect_reverted"] is not None
    assert "DDoS" not in store.read_file(NETWORK_PROC)


def test_undo_of_a_bulk_approval_touches_no_file(client, db, company, fake_llm):
    ids = _seed(db)
    client.post("/actions/bulk", json={"action_ids": [ids["action_id"]], "decision": "approve"})
    body = client.post(f"/actions/{ids['action_id']}/undo").json()
    assert body["status"] == "pending" and body["effect_reverted"] is None and body["effect_reapplied"] is None
    redo = client.post(f"/actions/{ids['action_id']}/undo").json()
    assert redo["status"] == "approved" and redo["effect_reapplied"] is None
    assert fake_llm.calls == []


def test_undo_reports_a_kept_edit_when_the_file_has_newer_versions(client, db, company, fake_llm):
    ids = _seed(db)
    client.post(f"/actions/{ids['action_id']}/approve")
    store.write_new_version(NETWORK_PROC, store.read_file(NETWORK_PROC) + "\n- later edit\n", origin="agent")
    body = client.post(f"/actions/{ids['action_id']}/undo").json()
    assert body["status"] == "pending" and body["effect_reverted"] is None
    assert any("file edit kept" in s for s in body["side_effects_not_reversed"])
    assert "later edit" in store.read_file(NETWORK_PROC)
