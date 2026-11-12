"""
Unit tests for app/eval_summary.py. Points _COMBINED_PATH/_BENCHMARK_DIR
at a tmp_path so these never depend on this machine's real eval run
history (which is real, present data, but not something a test should be
coupled to).
"""

import json

from app import eval_summary
from app.config import settings


def test_returns_none_when_no_eval_has_ever_run(tmp_path, monkeypatch):
    monkeypatch.setattr(eval_summary, "_COMBINED_PATH", tmp_path / "eval_results.json")
    monkeypatch.setattr(eval_summary, "_BENCHMARK_DIR", tmp_path / "benchmark")
    assert eval_summary.load_latest_eval_summary() is None


def test_prefers_the_combined_file_entry_for_the_configured_model(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "llm_model", "vendor/model-a")
    combined = tmp_path / "eval_results.json"
    combined.write_text(json.dumps({
        "sample_limit": 20,
        "models": {
            "vendor/model-a": {
                "model": "vendor/model-a", "sample_size": 20, "labeled_sample_size": 14,
                "accuracy_on_labeled": 0.93, "results": [{"huge": "payload"}], "per_change_type": {"x": 1},
            },
            "vendor/model-b": {"model": "vendor/model-b", "accuracy_on_labeled": 0.5},
        },
    }), encoding="utf-8")
    monkeypatch.setattr(eval_summary, "_COMBINED_PATH", combined)
    monkeypatch.setattr(eval_summary, "_BENCHMARK_DIR", tmp_path / "benchmark")

    result = eval_summary.load_latest_eval_summary()
    assert result["accuracy_on_labeled"] == 0.93
    assert result["labeled_sample_size"] == 14
    # Heavy per-row fields are stripped — this is a summary, not a dump.
    assert "results" not in result
    assert "per_change_type" not in result


def test_falls_back_to_the_per_model_benchmark_file_when_not_in_the_combined_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "llm_model", "vendor/model-c")
    benchmark_dir = tmp_path / "benchmark"
    benchmark_dir.mkdir()
    (benchmark_dir / "results_vendor__model-c.json").write_text(json.dumps({
        "model": "vendor/model-c", "sample_size": 10, "labeled_sample_size": 8, "accuracy_on_labeled": 0.75,
    }), encoding="utf-8")
    monkeypatch.setattr(eval_summary, "_COMBINED_PATH", tmp_path / "eval_results.json")  # does not exist
    monkeypatch.setattr(eval_summary, "_BENCHMARK_DIR", benchmark_dir)

    result = eval_summary.load_latest_eval_summary()
    assert result["accuracy_on_labeled"] == 0.75


def test_model_slug_matches_eval_diffs_own_replacement_rule():
    assert eval_summary._model_slug("google/gemma-4-31b-it") == "google__gemma-4-31b-it"
    assert eval_summary._model_slug("qwen3.6:27b") == "qwen3.6-27b"
