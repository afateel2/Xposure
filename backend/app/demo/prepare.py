"""
`python -m app.demo.prepare`: warm the caches once so the live demo replays fast.

A cold end-to-end run makes about 250 sequential LLM calls (about 15 minutes).
This command makes the same calls ONCE, in parallel with a thread pool
(retry and backoff for rate limits), and stores each real model answer in the
llm_cache table (app/llm_cache.py). It also fills the on-disk embedding cache
(app/embedding_cache.py) by ingesting ECC-2:2024 once. Afterwards a demo
reset followed by a scan replays the identical prompts from the local cache
and reaches "awaiting review" in roughly a minute, and the run log says how
many answers came from the cache.

Steps (idempotent, safe to run again; entries that already exist are hits):
  1. apply the alembic migrations (creates llm_cache if missing)
  2. reset to BASELINE (this reloads the org graph from data/org/demo_org.yaml,
     so the impact prompts are the ones the demo will use)
  3. fetch ECC-2:2024 from the portal mirror and ingest it (fills the
     embedding cache)
  4. classify every changed clause pair in parallel (fills the classify cache)
  5. run the real diff (answered from the cache) to create the Change rows
  6. trace impact for every material change in parallel (fills the impact cache)
  7. reset to BASELINE again

Options:
  --workers N   thread pool size (default 10)
  --limit N     only warm the first N classify prompts (mechanics check: skips
                steps 5 and 6, and the demo will still have cold misses)
  --no-final-reset   leave the filled state in place (debugging)

The org graph must already be in its final form (demo_org.yaml) and the
prompts final (llm.py, impact.py) before the full run: any change to a prompt
or to a node's attributes changes its cache key and that entry is simply
warmed again next time.
"""

from __future__ import annotations

import argparse
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import embedding_cache, llm, llm_cache
from ..config import settings
from ..db import session as db_session
from ..db.models import Change, Clause, Regulation, RegulationVersion, Regulator
from . import constants as C
from . import mirror


# ── Retry with backoff ────────────────────────────────────────────────────

def _is_retryable(exc: Exception) -> bool:
    name = type(exc).__name__
    if name in {"RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError"}:
        return True
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and (status == 429 or status >= 500)


def with_retry(fn: Callable[[], Any], *, attempts: int = 6, base: float = 2.0,
               sleep: Callable[[float], None] = time.sleep) -> Any:
    """Call fn(); on a rate limit or transient server error wait
    base * 2^n plus jitter and try again. Any other exception, and the last
    retryable one, propagate."""
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            if attempt == attempts - 1 or not _is_retryable(exc):
                raise
            sleep(base * (2 ** attempt) + random.uniform(0, 1))
    raise AssertionError("unreachable")


# ── Which prompts the real pipeline will send ─────────────────────────────

def classify_inputs(db: Session, from_label: str, to_label: str) -> list[tuple[str, str, str]]:
    """(old_text, new_text, match_kind) for every pair diff.run_diff() will
    classify. Mirrors run_diff's own alignment and identical-text skip using
    the same functions; tests/unit/test_demo_prepare.py checks the two agree."""
    from .. import diff
    from ..retriever import get_vectors_for_version

    regulation = db.scalar(
        select(Regulation).join(Regulator).where(
            Regulator.code == C.BASELINE_REGULATOR, Regulation.code == C.BASELINE_REGULATION
        )
    )
    versions = {
        v.version_label: v for v in db.scalars(
            select(RegulationVersion).where(RegulationVersion.regulation_id == regulation.id)
        )
    }
    from_v, to_v = versions[from_label], versions[to_label]
    from_clauses = list(db.scalars(select(Clause).where(Clause.version_id == from_v.id)))
    to_clauses = list(db.scalars(select(Clause).where(Clause.version_id == to_v.id)))
    pairs = diff.align_clauses(
        from_clauses, to_clauses,
        get_vectors_for_version(C.BASELINE_REGULATOR, C.BASELINE_REGULATION, from_label),
        get_vectors_for_version(C.BASELINE_REGULATOR, C.BASELINE_REGULATION, to_label),
    )
    out: list[tuple[str, str, str]] = []
    for p in pairs:
        if p["old"] and p["new"] and p["old"].text_en == p["new"].text_en:
            continue
        out.append((p["old"].text_en if p["old"] else "", p["new"].text_en if p["new"] else "", p["match_kind"]))
    return out


# ── Parallel warm-up ──────────────────────────────────────────────────────

class WarmStats:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.total = 0
        self.failed: list[str] = []
        self.latencies: list[float] = []

    def summary(self) -> dict[str, Any]:
        lat = sorted(self.latencies)
        return {
            "total": self.total, "completed": len(lat), "failed": len(self.failed),
            "median_call_seconds": round(lat[len(lat) // 2], 2) if lat else None,
            "max_call_seconds": round(lat[-1], 2) if lat else None,
            "sum_call_seconds": round(sum(lat), 1),
        }


def warm_parallel(label: str, jobs: list[Callable[[], Any]], workers: int) -> WarmStats:
    stats = WarmStats()
    stats.total = len(jobs)

    def run(job: Callable[[], Any]) -> None:
        started = time.monotonic()
        with_retry(job)
        elapsed = time.monotonic() - started
        with stats.lock:
            stats.latencies.append(elapsed)

    started = time.monotonic()
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run, job): i for i, job in enumerate(jobs)}
        for future in as_completed(futures):
            done += 1
            try:
                future.result()
            except Exception as exc:
                stats.failed.append(f"job {futures[future]}: {type(exc).__name__}: {exc}")
            if done % 10 == 0 or done == len(jobs):
                print(f"  [{label}] {done}/{len(jobs)} done, {len(stats.failed)} failed, "
                      f"{time.monotonic() - started:.0f}s elapsed", flush=True)
    return stats


def impact_jobs(db: Session, changes: list[Change]) -> list[Callable[[], Any]]:
    """One job per (material change, impacted node): the exact call
    compute_impact_for_change() will make."""
    from .. import impact

    jobs: list[Callable[[], Any]] = []
    for change in changes:
        seeds = impact.find_seed_control_mappings(db, change)
        if not seeds:
            continue
        for node, path in impact.traverse_impacted_nodes(db, seeds):
            jobs.append(lambda c=change, n=node, p=path: impact.impact_note(c, n, p))
    return jobs


# ── Company file edits (approve then undo through the real API path) ─────

#: The flows the demo recording shows. `clause` is matched on normalized
#: clause segments, `node_contains` against the impacted node's name.
DEMO_EDIT_FLOWS: list[dict[str, Any]] = [
    {"clause": (2, 5, 3, 9), "type": "update_procedure", "node_contains": "Network Security Procedure"},
    {"clause": (2, 5, 3, 9), "type": "technical_change", "node_contains": "ICU-200"},
    {"clause": (2, 5, 3, 9), "type": "technical_change", "node_contains": "SCADA-Lite"},
    {"clause": (2, 8, 3, 1), "type": "update_policy", "node_contains": "Cryptography Policy"},
]


def _sign_in_demo_reviewer(client: Any) -> None:
    """Every state-changing endpoint requires a signed-in reviewer (app/auth.py),
    so the TestClient used to warm the company-edit cache below needs a real
    session cookie too, exactly as a browser would get one from /login. Reuses
    scripts/seed_users.py's DEMO_USER_PASSWORD from .env (not a Settings field,
    read the same way seed_users.py writes it); raises with a clear message if
    seed_users.py has not been run yet, rather than warming nothing silently."""
    env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
    password = None
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("DEMO_USER_PASSWORD="):
                password = line.split("=", 1)[1].strip() or None
    if not password:
        raise RuntimeError(
            "DEMO_USER_PASSWORD not found in .env: run scripts/seed_users.py first "
            "so warm_company_edits() has a reviewer session to sign in with."
        )
    res = client.post("/auth/login", json={"email": "compliance@eastern-industrial.example", "password": password})
    if res.status_code != 200:
        raise RuntimeError(f"Demo reviewer sign-in failed ({res.status_code}): {res.text[:200]}")


def warm_company_edits(flows: list[dict[str, Any]] | None = None, client: Any = None) -> list[dict[str, Any]]:
    """For each demo flow: find the pending action, POST /actions/{id}/approve
    (the executor asks the model to edit the company file, and stores the
    answer in app/company's own prompt-keyed cache), then POST
    /actions/{id}/undo (the file goes back to its baseline content and the
    action to pending). Runs through the same FastAPI app the UI calls.
    Sequential on purpose: each flow starts from baseline file content, so
    its prompt is byte-identical to the one the recording will send."""
    from fastapi.testclient import TestClient

    from .. import impact
    from ..db.models import Action

    if client is None:
        from ..main import app

        client = TestClient(app)
        _sign_in_demo_reviewer(client)
    results: list[dict[str, Any]] = []
    for flow in flows or DEMO_EDIT_FLOWS:
        with Session(db_session.get_engine()) as db:
            candidates = [
                a for a in db.scalars(select(Action).where(Action.type == flow["type"], Action.status == "pending"))
                if (a.payload_json or {}).get("impact_node_name", "").find(flow["node_contains"]) >= 0
                and impact.normalized_segments((a.payload_json or {}).get("clause_id")) == tuple(flow["clause"])
            ]
            target = candidates[0].id if candidates else None
        entry: dict[str, Any] = {"flow": f"{'-'.join(map(str, flow['clause']))} {flow['type']} {flow['node_contains']}",
                                 "action_id": target}
        if target is None:
            entry["status"] = "not_found"
            results.append(entry)
            continue
        started = time.monotonic()
        approved = client.post(f"/actions/{target}/approve")
        entry["approve_http"] = approved.status_code
        entry["approve_seconds"] = round(time.monotonic() - started, 1)
        body = approved.json() if approved.status_code == 200 else {"detail": approved.text[:200]}
        effect = body.get("effect") if isinstance(body.get("effect"), dict) else None
        entry["file"] = effect.get("path") if effect else None
        entry["was_cached"] = effect.get("cached") if effect else None
        entry["note"] = body.get("effect_note") or body.get("detail")
        undone = client.post(f"/actions/{target}/undo")
        entry["undo_http"] = undone.status_code
        ok = approved.status_code == 200 and undone.status_code == 200 and effect is not None
        entry["status"] = "warmed" if ok else "failed"
        results.append(entry)
        print(f"  {entry}")
    return results


# ── Orchestration ─────────────────────────────────────────────────────────

def _upgrade_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(cfg, "head")


def run(workers: int = 10, limit: int | None = None, final_reset: bool = True) -> dict[str, Any]:
    from ..agent import graph
    from . import baseline

    report: dict[str, Any] = {"workers": workers, "limit": limit, "model": settings.llm_model}
    t0 = time.monotonic()
    _upgrade_migrations()
    with llm_cache.activated():
        print("1/7 reset to baseline (reloads the org graph)")
        baseline.reset_to_baseline(source="prepare")

        print("2/7 fetch and ingest ECC-2:2024 from the portal mirror")
        t = time.monotonic()
        mirror.seed_mirror()
        with Session(db_session.get_engine()) as db:
            new_docs = [d for d in mirror.list_portal(db) if d.status == "new"]
        if not new_docs:
            raise SystemExit("The portal mirror has no new document. Put ECC-2-2024 in backend/data/portal_mirror/nca/.")
        emb_before = embedding_cache.stats_snapshot()
        for doc in new_docs:
            mirror.fetch(doc)
            known = graph.KNOWN_SOURCES[doc.filename]
            graph._load_ingest()(
                known.regulator_code, known.regulation_code, known.version_label,
                graph.SOURCES_DIR / doc.path, code_before_text=known.code_before_text, replace=False,
            )
        emb_after = embedding_cache.stats_snapshot()
        report["ingest_seconds"] = round(time.monotonic() - t, 1)
        report["embeddings"] = {
            "texts": emb_after["texts"] - emb_before["texts"],
            "from_cache": emb_after["cache_hits"] - emb_before["cache_hits"],
        }

        print("3/7 classify every changed clause pair in parallel")
        with Session(db_session.get_engine()) as db:
            inputs = classify_inputs(db, C.BASELINE_VERSION, C.NEW_VERSION)
        report["classify_prompts"] = len(inputs)
        selected = inputs[:limit] if limit else inputs
        t = time.monotonic()
        cls = warm_parallel(
            "classify", [lambda a=a: llm.classify_change(*a) for a in selected], workers
        )
        report["classify"] = {**cls.summary(), "seconds": round(time.monotonic() - t, 1), "errors": cls.failed[:5]}

        if limit:
            print("(limit given: skipping the real diff and the impact warm-up)")
        else:
            print("4/7 run the real diff (answered from the cache) to create the Change rows")
            from .. import diff
            t = time.monotonic()
            diff.run_diff(
                C.BASELINE_REGULATOR, C.BASELINE_REGULATION, C.BASELINE_VERSION, C.NEW_VERSION,
                dry_run=False, replace=False,
            )
            report["diff_seconds"] = round(time.monotonic() - t, 1)

            print("5/7 trace impact for every material change in parallel")
            with Session(db_session.get_engine()) as db:
                changes = list(db.scalars(select(Change).where(Change.material.is_(True)).order_by(Change.id)))
                jobs = impact_jobs(db, changes)
            report["material_changes"] = len(changes)
            report["impact_prompts"] = len(jobs)
            t = time.monotonic()
            imp = warm_parallel("impact", jobs, workers)
            report["impact"] = {**imp.summary(), "seconds": round(time.monotonic() - t, 1), "errors": imp.failed[:5]}

            if not report["classify"]["failed"] and not report["impact"]["failed"]:
                print("5b/7 run the real agent graph once (all model answers now come from the cache)")
                before = llm_cache.stats_snapshot()
                t = time.monotonic()
                graph.run_once(thread_id=f"demo-prepare-{int(time.time())}")
                after = llm_cache.stats_snapshot()
                report["graph_replay_seconds"] = round(time.monotonic() - t, 1)
                report["graph_replay_llm"] = {
                    k: {f: after.get(k, {}).get(f, 0) - before.get(k, {}).get(f, 0) for f in ("calls", "cache_hits")}
                    for k in ("classify", "impact")
                }

                print("5c/7 approve then undo the demo-flow actions so the company file edits are cached")
                t = time.monotonic()
                report["company_edits"] = warm_company_edits()
                report["company_edit_seconds"] = round(time.monotonic() - t, 1)

        if final_reset:
            print("6/7 reset to baseline again (restores the company files too)")
            baseline.reset_to_baseline(source="prepare")
        else:
            print("6/7 (final reset skipped)")

    report["cache_entries"] = llm_cache.count_entries()
    report["total_seconds"] = round(time.monotonic() - t0, 1)
    failed = (report.get("classify", {}).get("failed", 0)) + (report.get("impact", {}).get("failed", 0))
    edits_bad = [e for e in report.get("company_edits", []) if e["status"] != "warmed"]
    report["company_edits_not_warmed"] = len(edits_bad)
    report["ok"] = failed == 0 and not edits_bad
    print("7/7 done")
    return report


def main() -> None:
    # Windows' console defaults stdout to the system codepage (cp1252), which
    # cannot encode Arabic; the progress lines below quote real clause and
    # company-node text, some of it Arabic, so a plain print() would crash
    # the whole warm-up run over a log line. UTF-8 output never does.
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Warm the demo LLM and embedding caches, then reset to baseline")
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--limit", type=int, default=None, help="warm only the first N classify prompts")
    parser.add_argument("--no-final-reset", action="store_true")
    args = parser.parse_args()
    if not settings.demo_mode:
        raise SystemExit("DEMO_MODE is off: the caches and the reset are disabled.")
    report = run(workers=args.workers, limit=args.limit, final_reset=not args.no_final_reset)
    import json

    print(json.dumps(report, indent=2, ensure_ascii=False))
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
