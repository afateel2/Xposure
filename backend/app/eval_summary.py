"""
Surfaces tests/eval_diff.py's own output for the product (Settings screen's
trust-calibration display) — a pure file read, no new computation, no
import of the tests/ package (app/ stays independent of tests/ as a
layering matter; the file format is the only contract between them).

Returns None, honestly, if no eval has ever been run — matching this
project's "no silent fallback" discipline (docs/PLAN.md section 7). A
missing number must never be quietly reported as 0% or omitted from the
response without saying why.
"""

import json
from pathlib import Path
from typing import Any

from .config import settings

_TESTS_DIR = Path(__file__).parent.parent / "tests"
_COMBINED_PATH = _TESTS_DIR / "eval_results.json"
_BENCHMARK_DIR = _TESTS_DIR / "benchmark"


def _model_slug(model: str) -> str:
    # Mirrors tests/eval_diff.py's own _model_slug() exactly (same
    # replacement rule) so per-model filenames resolve identically.
    return model.replace("/", "__").replace(":", "-")


def _strip_heavy_fields(summary: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in summary.items() if k not in ("results", "per_change_type")}


def load_latest_eval_summary() -> dict[str, Any] | None:
    """Prefers the entry for the CURRENTLY CONFIGURED model
    (settings.llm_model) inside the combined tests/eval_results.json, if
    present — a trust number is only honest if it's for the model actually
    running, not whichever candidate was benchmarked most recently. Falls
    back to that same model's own tests/benchmark/results_<slug>.json.
    Returns None if neither exists."""
    if _COMBINED_PATH.exists():
        combined = json.loads(_COMBINED_PATH.read_text(encoding="utf-8"))
        models = combined.get("models", {})
        if settings.llm_model in models:
            return _strip_heavy_fields(models[settings.llm_model])

    per_model_path = _BENCHMARK_DIR / f"results_{_model_slug(settings.llm_model)}.json"
    if per_model_path.exists():
        return _strip_heavy_fields(json.loads(per_model_path.read_text(encoding="utf-8")))

    return None
