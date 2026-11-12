"""
M9 evaluation harness. Two things it does, deliberately kept in one script
per the takeoff prompt's naming (`python -m tests.eval_diff`) rather than
split into a separate "quick compare" tool:

1. Structured-output validity + latency for whichever model is currently
   configured in .env (LLM_MODEL) — this works today, no ground truth
   needed, and is exactly what "test this model" means before any
   labeling has happened.
2. Precision/recall per change_type, once backend/tests/benchmark/
   ecc_v1_v2_labels.csv has real labeled rows (scaffolded below with a
   handful of example rows this session already has strong grounding
   for — see docs/PLAN.md's optimization-pass notes on clause 2-2-3-2 and
   the NCA changelog-annex finding, which may eventually supersede
   hand-labeling entirely as a ground-truth source).

Run as:
  python -m tests.eval_diff [--limit N] [--out results_<slug>.json]

Reuses app.diff's alignment (deterministic, already verified against real
data — see docs/PLAN.md) to build a FIXED, repeatable sample of aligned
clause pairs, so the same pairs are used across separate invocations with
different LLM_MODEL values in .env — that's what makes the resulting
per-model JSON files actually comparable to each other.
"""

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import llm
from app.config import settings
from app.db.models import Clause, Regulation, RegulationVersion, Regulator
from app.db.session import get_engine
from app.diff import align_clauses
from app.retriever import get_vectors_for_version

BENCHMARK_DIR = Path(__file__).parent / "benchmark"
LABELS_CSV = BENCHMARK_DIR / "ecc_v1_v2_labels.csv"


def _model_slug(model_name: str) -> str:
    return model_name.replace("/", "__").replace(":", "_")


def load_sample_pairs(regulator_code: str = "nca", regulation_code: str = "ecc",
                       from_label: str = "1-2018", to_label: str = "2-2024",
                       limit: int | None = None) -> list[dict]:
    """The same deterministic pair-selection every invocation, regardless
    of which model is configured — order comes from align_clauses(), which
    is itself deterministic (exact matches sorted by normalized segments,
    then Hungarian assignment), so results across separate model runs are
    genuinely comparing the same inputs."""
    engine = get_engine()
    with Session(engine) as db:
        regulation = db.scalar(
            select(Regulation).join(Regulator).where(
                Regulator.code == regulator_code, Regulation.code == regulation_code
            )
        )
        from_version = db.scalar(select(RegulationVersion).where(
            RegulationVersion.regulation_id == regulation.id, RegulationVersion.version_label == from_label,
        ))
        to_version = db.scalar(select(RegulationVersion).where(
            RegulationVersion.regulation_id == regulation.id, RegulationVersion.version_label == to_label,
        ))
        from_clauses = list(db.scalars(select(Clause).where(Clause.version_id == from_version.id)))
        to_clauses = list(db.scalars(select(Clause).where(Clause.version_id == to_version.id)))
        from_vectors = get_vectors_for_version(regulator_code, regulation_code, from_label)
        to_vectors = get_vectors_for_version(regulator_code, regulation_code, to_label)
        pairs = align_clauses(from_clauses, to_clauses, from_vectors, to_vectors)

        # detach into plain dicts before the session closes
        sample = []
        for p in pairs:
            old_c, new_c = p["old"], p["new"]
            if old_c and new_c and old_c.text_en == new_c.text_en:
                continue  # byte-identical — nothing to classify, same skip as run_diff()
            sample.append({
                "old_clause_id": old_c.clause_id if old_c else None,
                "new_clause_id": new_c.clause_id if new_c else None,
                "old_text": old_c.text_en if old_c else "",
                "new_text": new_c.text_en if new_c else "",
                "match_kind": p["match_kind"],
            })
        if limit:
            # Prioritize pairs that have a ground-truth label so a small
            # --limit still produces real accuracy signal instead of
            # landing entirely on unlabeled exact-id matches from the
            # start of the (large) domain-1 block.
            labels = _load_labels()
            labeled = [p for p in sample if (p["old_clause_id"], p["new_clause_id"]) in labels]
            unlabeled = [p for p in sample if (p["old_clause_id"], p["new_clause_id"]) not in labels]
            sample = (labeled + unlabeled)[:limit]
        return sample


def _load_labels() -> dict[tuple[str | None, str | None], str]:
    if not LABELS_CSV.exists():
        return {}
    out = {}
    with open(LABELS_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["old_clause_id"] or None, row["new_clause_id"] or None)
            out[key] = row["expected_change_type"]
    return out


def run_eval(limit: int | None, out_path: Path | None) -> dict:
    model = settings.llm_model
    base_url = settings.llm_base_url
    print(f"Model: {model}")
    print(f"Base URL: {base_url}")

    pairs = load_sample_pairs(limit=limit)
    print(f"Sample: {len(pairs)} aligned clause pairs\n")

    labels = _load_labels()
    results = []
    n_valid = 0
    latencies = []

    for i, pair in enumerate(pairs, 1):
        old_id = pair["old_clause_id"] or "-"
        new_id = pair["new_clause_id"] or "-"
        t0 = time.time()
        try:
            classification = llm.classify_change(pair["old_text"], pair["new_text"], pair["match_kind"])
            elapsed = time.time() - t0
            latencies.append(elapsed)
            n_valid += 1
            status = "OK"
        except Exception as exc:
            elapsed = time.time() - t0
            latencies.append(elapsed)
            classification = None
            status = f"FAIL: {type(exc).__name__}: {exc}"

        expected = labels.get((pair["old_clause_id"], pair["new_clause_id"]))
        results.append({
            "old_clause_id": pair["old_clause_id"],
            "new_clause_id": pair["new_clause_id"],
            "match_kind": pair["match_kind"],
            "predicted_change_type": classification["change_type"] if classification else None,
            "confidence": classification["confidence"] if classification else None,
            "expected_change_type": expected,
            "correct": (expected == classification["change_type"]) if (expected and classification) else None,
            "latency_s": round(elapsed, 2),
            "status": status,
        })
        print(f"  [{i}/{len(pairs)}] {old_id:14s} -> {new_id:14s} {status:6s} "
              f"{(classification['change_type'] if classification else ''):16s} "
              f"({elapsed:.2f}s)")

    validity_rate = n_valid / len(pairs) if pairs else 0.0
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

    labeled = [r for r in results if r["correct"] is not None]
    accuracy = (sum(1 for r in labeled if r["correct"]) / len(labeled)) if labeled else None

    # Precision/recall per change_type, only meaningful once labels exist.
    # tp is tracked once per row (under whichever type key the row's
    # actually-correct prediction shares — predicted == expected exactly
    # when correct, so incrementing under either key is equivalent); a
    # type only appears here at all once something either expected or
    # predicted it, so a type nothing touched is simply absent rather
    # than a hollow all-zero entry.
    per_type: dict[str, dict[str, int | float | None]] = {}

    def _bucket(t: str) -> dict[str, int | float | None]:
        return per_type.setdefault(t, {"tp": 0, "total_expected": 0, "total_predicted": 0})

    for r in labeled:
        _bucket(r["expected_change_type"])["total_expected"] += 1
        if r["predicted_change_type"]:
            _bucket(r["predicted_change_type"])["total_predicted"] += 1
        if r["correct"]:
            _bucket(r["expected_change_type"])["tp"] += 1

    for t, counts in per_type.items():
        precision = counts["tp"] / counts["total_predicted"] if counts["total_predicted"] else None
        recall = counts["tp"] / counts["total_expected"] if counts["total_expected"] else None
        counts["precision"] = round(precision, 3) if precision is not None else None
        counts["recall"] = round(recall, 3) if recall is not None else None
        counts["f1"] = (
            round(2 * precision * recall / (precision + recall), 3)
            if precision and recall
            else None
        )

    summary = {
        "model": model,
        "base_url": base_url,
        "sample_size": len(pairs),
        "structured_output_validity_rate": round(validity_rate, 3),
        "avg_latency_s": round(avg_latency, 2),
        "labeled_sample_size": len(labeled),
        "accuracy_on_labeled": round(accuracy, 3) if accuracy is not None else None,
        "per_change_type": per_type,
        "results": results,
    }

    print(f"\n{'='*60}")
    print(f"Model: {model}")
    print(f"Structured-output validity: {validity_rate:.1%} ({n_valid}/{len(pairs)})")
    print(f"Avg latency: {avg_latency:.2f}s/clause")
    if accuracy is not None:
        print(f"Accuracy on {len(labeled)} labeled pairs: {accuracy:.1%}")
        print("Per change_type (precision / recall / f1, over expected+predicted counts):")
        for t in sorted(per_type):
            c = per_type[t]
            precision_s = f"{c['precision']:.0%}" if c["precision"] is not None else "n/a"
            recall_s = f"{c['recall']:.0%}" if c["recall"] is not None else "n/a"
            f1_s = f"{c['f1']:.0%}" if c["f1"] is not None else "n/a"
            print(f"    {t:16s} precision={precision_s:>5s} recall={recall_s:>5s} f1={f1_s:>5s} (expected={c['total_expected']}, predicted={c['total_predicted']})")
    else:
        print(f"No labeled pairs yet — see {LABELS_CSV.relative_to(Path(__file__).parent.parent)} to add ground truth.")
    print(f"{'='*60}\n")

    if out_path is None:
        BENCHMARK_DIR.mkdir(exist_ok=True)
        out_path = BENCHMARK_DIR / f"results_{_model_slug(model)}.json"
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved: {out_path}")

    return summary


# The four candidate models from the takeoff prompt section 5, addressed
# the way OpenRouter names them (see docs/PLAN.md section 3) — the same
# four already benchmarked once (structured-output validity/latency) in
# the earlier pass; --all-models re-runs all four now that the labeled
# set actually exercises every change_type but 'renumbered' (see
# tests/benchmark/ecc_v1_v2_labels.csv's own notes on why that one has no
# real example: align_clauses() currently produces zero
# renumbered_candidate pairs against this corpus).
CANDIDATE_MODELS: tuple[str, ...] = (
    "google/gemma-4-31b-it",
    "openai/gpt-oss-20b",
    "qwen/qwen3.6-27b",
    "qwen/qwen3.6-35b-a3b",
)


def run_all_models(limit: int | None) -> dict:
    """Runs run_eval() once per candidate model, each as a separate
    subprocess with LLM_MODEL overridden in that subprocess's environment
    only (never touching .env on disk) — necessary because
    app.config.settings is a module-level singleton read once at import
    time, so a single process can only ever exercise the model .env
    already names. Combines every model's summary into ONE file,
    tests/eval_results.json, matching the takeoff prompt's exact naming
    (section 3/M9) — each per-model run also still writes its own
    tests/benchmark/results_<slug>.json, unchanged.
    """
    import os
    import subprocess
    import sys

    combined: dict[str, Any] = {"sample_limit": limit, "models": {}}
    for model in CANDIDATE_MODELS:
        print(f"\n{'#'*60}\n# {model}\n{'#'*60}")
        env = {**os.environ, "LLM_MODEL": model}
        out_path = BENCHMARK_DIR / f"results_{_model_slug(model)}.json"
        args = [sys.executable, "-m", "tests.eval_diff", "--out", str(out_path)]
        if limit is not None:
            args += ["--limit", str(limit)]
        subprocess.run(args, cwd=Path(__file__).parent.parent, env=env, check=True)
        combined["models"][model] = json.loads(out_path.read_text(encoding="utf-8"))

    combined_path = Path(__file__).parent / "eval_results.json"
    combined_path.write_text(json.dumps(combined, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nCombined results for all {len(CANDIDATE_MODELS)} models saved: {combined_path}")
    return combined


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="M9 evaluation: structured-output validity, latency, and (once labeled) precision/recall per change_type")
    parser.add_argument("--limit", type=int, default=20, help="number of aligned pairs to test (default 20 — comfortably covers every row in ecc_v1_v2_labels.csv plus a few unlabeled pairs for validity-rate signal)")
    parser.add_argument("--out", type=Path, default=None, help="output JSON path for a single-model run (default: tests/benchmark/results_<model_slug>.json)")
    parser.add_argument("--all-models", action="store_true", help="run every model in CANDIDATE_MODELS (each a subprocess with LLM_MODEL overridden) and write tests/eval_results.json")
    args = parser.parse_args()
    if args.all_models:
        run_all_models(args.limit)
    else:
        run_eval(args.limit, args.out)
