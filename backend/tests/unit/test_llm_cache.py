"""
LLM result cache and embedding cache (demo mode only).

SQLite in memory, as in test_agent.py. The model client is a mock: the point
is what the cache does around it: same prompt hits, any change to the model
or prompt misses, nothing is stored unless the cache is active, and an answer
that fails validation is never stored.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import embedding_cache, impact, llm, llm_cache
from app.config import settings
from app.db.models import Change, OrgNode

from .demo_fixtures import demo_env  # noqa: F401  (fixture)


def _classify_response(change_type="tightened", confidence=0.9):
    args = {"change_type": change_type, "confidence": confidence, "summary_en": "s", "summary_ar": "ص"}
    call = SimpleNamespace(function=SimpleNamespace(arguments=json.dumps(args)))
    message = SimpleNamespace(tool_calls=[call])
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])


def _client(response):
    client = MagicMock()
    client.chat.completions.create.return_value = response
    return client


# ── keys ──────────────────────────────────────────────────────────────────

def test_key_is_deterministic_and_sensitive_to_every_input():
    msgs = [{"role": "user", "content": "a"}]
    tools = [{"type": "function"}]
    base = llm_cache.make_key("classify", "m", msgs, tools)
    assert base == llm_cache.make_key("classify", "m", msgs, tools)
    assert len(base) == 64
    assert base != llm_cache.make_key("impact", "m", msgs, tools)
    assert base != llm_cache.make_key("classify", "other-model", msgs, tools)
    assert base != llm_cache.make_key("classify", "m", [{"role": "user", "content": "b"}], tools)
    assert base != llm_cache.make_key("classify", "m", msgs, [{"type": "function", "x": 1}])


# ── activation ────────────────────────────────────────────────────────────

def test_cache_is_inactive_by_default_and_touches_no_table(demo_env):
    assert llm_cache.is_active() is False
    assert llm_cache.lookup("classify", "k") is None
    assert llm_cache.store("classify", "k", "m", {"a": 1}) is False
    with demo_env.session() as db:
        assert db.scalar(select(llm_cache.LlmCache)) is None


def test_activation_requires_demo_mode(demo_env, monkeypatch):
    with llm_cache.activated():
        assert llm_cache.is_active() is True
        monkeypatch.setattr(settings, "demo_mode", False)
        assert llm_cache.is_active() is False
    assert llm_cache.is_active() is False


def test_activation_is_reentrant():
    with llm_cache.activated():
        with llm_cache.activated():
            assert llm_cache.is_active()
        assert llm_cache.is_active()
    assert not llm_cache.is_active()


# ── lookup / store ────────────────────────────────────────────────────────

def test_store_then_lookup_returns_the_same_answer_and_counts_the_hit(demo_env):
    with llm_cache.activated():
        assert llm_cache.lookup("classify", "abc") is None  # miss
        assert llm_cache.store("classify", "abc", "m", {"change_type": "tightened"}) is True
        assert llm_cache.lookup("classify", "abc") == {"change_type": "tightened"}
        assert llm_cache.lookup("classify", "abc") == {"change_type": "tightened"}
    with demo_env.session() as db:
        row = db.get(llm_cache.LlmCache, "abc")
        assert row.hit_count == 2 and row.kind == "classify" and row.model == "m"
    stats = llm_cache.stats_snapshot()["classify"]
    assert stats == {"calls": 3, "cache_hits": 2}


def test_duplicate_store_is_not_an_error(demo_env):
    with llm_cache.activated():
        assert llm_cache.store("impact", "dup", "m", {"a": 1}) is True
        assert llm_cache.store("impact", "dup", "m", {"a": 2}) is False
        assert llm_cache.lookup("impact", "dup") == {"a": 1}


def test_missing_table_degrades_to_a_miss_not_a_crash(demo_env):
    with demo_env.engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE llm_cache")
    with llm_cache.activated():
        assert llm_cache.lookup("classify", "k") is None
        assert llm_cache.store("classify", "k", "m", {}) is False
    assert llm_cache.count_entries() == {"total": 0}


def test_stats_delta_between_snapshots(demo_env):
    with llm_cache.activated():
        before = llm_cache.stats_snapshot()
        llm_cache.lookup("impact", "x")
        llm_cache.store("impact", "x", "m", {"a": 1})
        llm_cache.lookup("impact", "x")
        after = llm_cache.stats_snapshot()
    assert llm_cache.stats_delta(before, after, "impact") == (2, 1)
    assert llm_cache.stats_delta(before, after, "classify") == (0, 0)


# ── classify_change integration ───────────────────────────────────────────

def test_classify_change_hits_the_cache_on_an_identical_prompt(demo_env):
    client = _client(_classify_response())
    with patch.object(llm, "get_client", return_value=client), llm_cache.activated():
        first = llm.classify_change("old text", "new text", "exact_id")
        second = llm.classify_change("old text", "new text", "exact_id")
        third = llm.classify_change("old text", "different new text", "exact_id")
    assert first == second
    assert client.chat.completions.create.call_count == 2  # third prompt differs
    assert third["change_type"] == "tightened"
    assert llm_cache.count_entries()["classify"] == 2


def test_classify_change_without_activation_never_caches(demo_env):
    client = _client(_classify_response())
    with patch.object(llm, "get_client", return_value=client):
        llm.classify_change("old", "new", "exact_id")
        llm.classify_change("old", "new", "exact_id")
    assert client.chat.completions.create.call_count == 2
    assert llm_cache.count_entries() == {"total": 0}


def test_classify_change_does_not_cache_an_invalid_answer(demo_env):
    bad = _client(_classify_response(change_type="not_a_type"))
    with patch.object(llm, "get_client", return_value=bad), llm_cache.activated():
        with pytest.raises(ValueError):
            llm.classify_change("old", "new", "exact_id")
    assert llm_cache.count_entries() == {"total": 0}


def test_cached_answer_is_revalidated_and_em_dash_stripped_on_the_way_out(demo_env):
    with llm_cache.activated():
        key = llm_cache.make_key(
            "classify", settings.llm_model, llm._build_classify_messages("o", "n", "exact_id"), llm._CLASSIFY_TOOL
        )
        llm_cache.store("classify", key, settings.llm_model, {
            "change_type": "relaxed", "confidence": 0.8, "summary_en": "a " + chr(0x2014) + " b", "summary_ar": "ص",
        })
        with patch.object(llm, "get_client", side_effect=AssertionError("must not call the model")):
            result = llm.classify_change("o", "n", "exact_id")
    assert result["summary_en"] == "a, b"


# ── impact_note integration ───────────────────────────────────────────────

def _impact_response():
    args = {"note_en": "note", "note_ar": "ملاحظة", "recommended_actions": ["update_policy"]}
    call = SimpleNamespace(function=SimpleNamespace(arguments=json.dumps(args)))
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]), finish_reason="stop")])


def test_impact_note_hits_the_cache_on_an_identical_prompt(demo_env):
    change = Change(id=1, regulation_id=1, from_version_id=1, to_version_id=2, match_kind="exact_id",
                    old_clause_id="2-5-3", new_clause_id="2-5-3", change_type="tightened", summary_en="s")
    node = OrgNode(id=5, type="policy", name="Access Control Policy", attrs_json={})
    path = {"seed": {"name": "ECC 2-5-3", "control_id": "2-5-3"}, "scope_match": "exact",
            "matched_clause_id": "2-5-3", "depth": 1, "summary": "ECC 2-5-3 -[stated_in]-> Access Control Policy"}
    client = _client(_impact_response())
    with patch.object(llm, "get_client", return_value=client), llm_cache.activated():
        a = impact.impact_note(change, node, path)
        b = impact.impact_note(change, node, path)
    assert a == b and a["recommended_actions"] == ["update_policy"]
    assert client.chat.completions.create.call_count == 1
    assert llm_cache.count_entries()["impact"] == 1


# ── embedding cache ───────────────────────────────────────────────────────

def test_embedding_cache_reads_back_identical_vectors_and_only_embeds_missing(demo_env):
    calls: list[list[str]] = []

    def fake_embed(texts):
        calls.append(list(texts))
        return [np.full(4, float(len(t)), dtype=np.float32).tolist() for t in texts]

    with llm_cache.activated():
        first = embedding_cache.embed_with_cache("model", ["aa", "bbb"], fake_embed)
        second = embedding_cache.embed_with_cache("model", ["aa", "bbb", "cccc"], fake_embed)
    assert calls == [["aa", "bbb"], ["cccc"]]
    assert second[:2] == first
    stats = embedding_cache.stats_snapshot()
    assert stats["cache_hits"] >= 2


def test_embedding_cache_is_bypassed_when_inactive(demo_env):
    calls = []
    embedding_cache.embed_with_cache("model", ["aa"], lambda t: calls.append(t) or [[1.0]])
    embedding_cache.embed_with_cache("model", ["aa"], lambda t: calls.append(t) or [[1.0]])
    assert len(calls) == 2
