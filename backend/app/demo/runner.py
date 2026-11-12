"""
The background scan: what "Scan now" does.

  1. portal   list the portal mirror and compare it with the versions the
              database already knows (a local folder, labelled so)
  2. fetch    "download" each new document: copy it from the mirror into
              backend/data/sources/ and verify the checksum
  3. the REAL agent graph (agent/graph.py: check_sources, ingest_new, diff,
     impact, prioritize, apply_policy, auto_execute, human_review), streamed
     node by node. Its human_review step is a real LangGraph interrupt: the
     run stops there, checkpointed in Postgres, and the UI's approve and
     dismiss buttons take over.

This module adds no pipeline logic. It starts the graph, listens to it (the
graph's own task events plus the progress hooks in diff.py and graph.py) and
translates what it hears into the stage checklist of GET /demo/run. Every
number shown is read from what the pipeline actually returned or stored.

Honesty rules enforced here:
  - the run says the portal is simulated by a local mirror;
  - it says how many model answers came from the local cache of an earlier
    identical run (llm_cache.py) and how many vectors from the embedding
    cache, versus how many were produced live;
  - it says the stage pause (DEMO_STAGE_PACING_MS) exists;
  - a failure marks the stage failed with the reason and the run failed. It
    is never turned into a success.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, embedding_cache, llm_cache, progress
from ..config import settings
from ..db import session as db_session
from ..db.models import Action, Clause, RegulationVersion
from . import constants as C
from . import mirror
from .tracker import TRACKER, DemoConflict

log = logging.getLogger(__name__)


# ── Public entry point (called by the route) ─────────────────────────────

def start_scan(*, actor: str = C.ACTOR_USER) -> dict[str, Any]:
    """Begin a scan in a background thread. One at a time: a second call
    while a scan runs returns the running run with already_running=True."""
    from ..agent import graph

    if not settings.demo_mode:
        raise DemoConflict("Demo mode is off (DEMO_MODE=false): the scan is disabled.")
    run_id = graph._new_run_id()
    if not TRACKER.try_start(run_id, actor=actor):
        snap = TRACKER.snapshot()
        return {"run_id": snap["run_id"], "status": snap["status"], "started_at": snap["started_at"],
                "already_running": True}
    thread = threading.Thread(target=_execute, args=(run_id,), name=f"demo-scan-{run_id}", daemon=True)
    TRACKER.attach_thread(thread)
    thread.start()
    snap = TRACKER.snapshot()
    return {"run_id": run_id, "status": snap["status"], "started_at": snap["started_at"], "already_running": False}


# ── The run ───────────────────────────────────────────────────────────────

def _execute(run_id: str) -> None:
    listener = _Listener(run_id)
    try:
        with llm_cache.activated():
            progress.set_listener(listener.on_event)
            _scan(run_id, listener)
    except (Exception, SystemExit) as exc:
        log.exception("demo scan %s failed", run_id)
        TRACKER.fail(f"{type(exc).__name__}: {exc}", error_type=type(exc).__name__)
    finally:
        progress.set_listener(None)


def _kb(n: int) -> str:
    return f"{n / 1024:.0f}"


def _edition(doc: "mirror.PortalDocument") -> str:
    """"ECC-2:2024" for regulation ecc, version label 2-2024."""
    return f"{(doc.regulation or '').upper()}-{(doc.version_label or '').replace('-', ':')}"


def _scan(run_id: str, listener: "_Listener") -> None:
    from ..agent import graph

    t = TRACKER

    # 1. portal -----------------------------------------------------------
    t.stage_start("portal", "Listing the documents published on the portal mirror.",
                  "جارٍ سرد الوثائق المنشورة في النسخة المحلية للبوابة.")
    mirror.seed_mirror()
    with Session(db_session.get_engine()) as db:
        docs = mirror.list_portal(db)
        pending_pairs = graph.pending_diff_pairs(db)
        pending_changes = graph.changes_needing_action(db)
        unfinished = bool(pending_pairs or pending_changes)
    if not docs:
        raise RuntimeError(
            "The portal mirror is empty. Place the regulator PDFs in backend/data/portal_mirror/nca/."
        )
    new_docs = [d for d in docs if d.status == "new"]
    known = [d for d in docs if d.status == "known"]
    attention = [d for d in docs if d.status in ("conflict", "unrecognized")]
    labels = ", ".join(_edition(d) for d in new_docs if d.version_label) or "none"
    t.stage_done(
        "portal",
        {"documents_on_portal": len(docs), "already_known": len(known), "new_documents": len(new_docs),
         "needs_attention": len(attention)},
        f"Published on the portal mirror: {len(docs)}. Already known: {len(known)}. New: {len(new_docs)} ({labels}).",
        f"المنشورة في النسخة المحلية للبوابة: {len(docs)}. المعروفة سابقًا: {len(known)}. "
        f"الجديدة: {len(new_docs)} ({labels}).",
    )

    if not new_docs and not unfinished:
        t.truncate_stages(["portal"])
        t.set_note(
            C.SIMULATED_PORTAL_NOTE_EN + " No new document was found since the last check, so nothing was run.",
            C.SIMULATED_PORTAL_NOTE_AR + " لم يُعثر على وثيقة جديدة منذ آخر فحص، لذلك لم يُنفَّذ أي شيء.",
        )
        t.finish("completed", {"new_documents": 0, "nothing_to_do": True})
        return

    # 2. fetch ------------------------------------------------------------
    t.stage_start("fetch", "Copying the new document from the portal mirror.",
                  "جارٍ نسخ الوثيقة الجديدة من النسخة المحلية للبوابة.")
    fetched: list[dict[str, Any]] = []
    for doc in new_docs:
        fetched.append(mirror.fetch(doc))
    if fetched:
        first = fetched[0]
        total = sum(f["size_bytes"] for f in fetched)
        t.stage_done(
            "fetch",
            {"files_fetched": len(fetched), "bytes": total},
            f"Fetched {len(fetched)} file(s), {_kb(total)} KB. {first['filename']} "
            f"(SHA-256 {first['sha256'][:12]}) copied from the local portal mirror and verified.",
            f"عدد الملفات المجلوبة: {len(fetched)}، والحجم: {_kb(total)} كيلوبايت. "
            f"تم نسخ {first['filename']} (SHA-256: {first['sha256'][:12]}) من النسخة المحلية للبوابة والتحقق منه.",
        )
    else:
        t.stage_done(
            "fetch", {"files_fetched": 0, "bytes": 0},
            "No new file to fetch. Resuming unfinished work from an earlier run.",
            "لا توجد ملفات جديدة للجلب. يجري استئناف عمل لم يكتمل من تشغيل سابق.",
        )

    # 3. the real graph ---------------------------------------------------
    thread_id = f"demo-{run_id}"
    initial = {"run_id": run_id, "started_at": graph._utc_now_iso()}
    config = {"configurable": {"thread_id": thread_id}}
    interrupt_result: dict[str, Any] | None = None
    try:
        # Cross-process serialization (graph.pipeline_lock's own docstring):
        # TRACKER.try_start() above only ever stopped a SECOND demo scan in
        # THIS process; it says nothing about a plain CLI `python -m
        # app.agent.graph` run racing this one. Non-blocking, same as
        # run_once/resume_run: fail fast and honest rather than silently
        # queuing behind a run that might take 15 minutes.
        with graph.pipeline_lock() as acquired:
            if not acquired:
                raise graph.PipelineBusy(
                    "Another pipeline run is already in progress (held the Postgres advisory lock)."
                )
            with graph.checkpointer() as saver:
                app = graph.build_graph(saver)
                for mode, data in app.stream(initial, config, stream_mode=["tasks", "updates"]):
                    if mode == "tasks":
                        if "input" in data:
                            listener.node_started(data["name"])
                        else:
                            if data.get("error"):
                                raise RuntimeError(f"Node {data['name']} failed: {data['error']}")
                            listener.node_finished(data["name"], data.get("result") or {}, data.get("interrupts") or [])
                    elif mode == "updates" and "__interrupt__" in data:
                        interrupt_result = {"__interrupt__": data["__interrupt__"]}
    except (Exception, SystemExit) as exc:
        # Same failure record run_once() writes, from a fresh session.
        audit.record_in_new_session(
            actor="agent:runner", event="run_failed",
            payload={"run_id": run_id, "thread_id": thread_id, "error": f"{type(exc).__name__}: {exc}"},
        )
        raise

    paused = False
    if interrupt_result is not None:
        paused = graph._report_interrupt(interrupt_result, thread_id)
    listener.finish(paused)


# ── Listener: graph and hook events -> stage checklist ───────────────────

class _Listener:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.llm_before: dict[str, dict[str, int]] = {}
        self.emb_before: dict[str, int] = {}
        self.classify_llm_before: dict[str, dict[str, int]] | None = None
        self.impact_llm_before: dict[str, dict[str, int]] | None = None
        self.aligned: dict[str, Any] | None = None
        self.classified = 0
        self.impact_total = 0
        self.impact_nodes = 0
        self.summary: dict[str, Any] = {}
        self.awaiting = 0
        self.llm_all_before = llm_cache.stats_snapshot()

    # graph task events ----------------------------------------------------

    def node_started(self, name: str) -> None:
        stage = C.NODE_STARTS_STAGE.get(name)
        if name == "check_sources":
            self.emb_before = embedding_cache.stats_snapshot()
            TRACKER.stage_start(
                "ingest", "Checking the sources folder and reading the new PDF.",
                "جارٍ فحص مجلد المصادر وقراءة ملف PDF الجديد.",
            )
        elif name == "diff":
            TRACKER.stage_start("align", "Matching clauses of the two versions.",
                                "جارٍ مطابقة بنود الإصدارين.")
        elif name == "impact":
            self.impact_llm_before = llm_cache.stats_snapshot()
            TRACKER.stage_start("impact", "Tracing each material change through the company's graph.",
                                "جارٍ تتبع كل تغيير جوهري عبر منظومة الشركة.")
        elif stage:
            TRACKER.stage_start(stage)

    def node_finished(self, name: str, result: dict[str, Any], interrupts: list[Any]) -> None:
        if name == "ingest_new":
            self._ingest_done(result)
        elif name == "diff":
            self._diff_done(result)
        elif name == "impact":
            self._impact_done(result)
        elif name == "prioritize":
            self._prioritize_done(result)
        elif name == "apply_policy":
            self._policy_done(result)
        elif name == "auto_execute":
            self._auto_done(result)
        elif name == "human_review":
            self._review_done(result, interrupts)

    # progress hooks -------------------------------------------------------

    def on_event(self, event: str, data: dict[str, Any]) -> None:
        if event == "diff.aligned":
            self._aligned(data)
        elif event == "diff.classified":
            self.classified = data["done"]
            TRACKER.stage_progress(
                "classify",
                {"changes_classified": data["done"], "to_classify": data["total"]},
                f"Classified {data['done']} of {data['total']} changes.",
                f"تم تصنيف {data['done']} من أصل {data['total']} تغييرًا.",
            )
        elif event == "impact.started":
            self.impact_total = data["total"]
            TRACKER.stage_progress(
                "impact", {"material_changes": data["total"]},
                f"Tracing {data['total']} material changes.", f"جارٍ تتبع {data['total']} تغييرًا جوهريًا.",
            )
        elif event == "impact.change_done":
            self.impact_nodes += data["impact_count"]
            TRACKER.stage_progress(
                "impact",
                {"changes_traced": data["index"], "material_changes": data["total"], "impacted_nodes": self.impact_nodes},
                f"Traced {data['index']} of {data['total']} material changes, {self.impact_nodes} impacted nodes so far.",
                f"تم تتبع {data['index']} من أصل {data['total']} تغييرًا جوهريًا، وعدد العناصر المتأثرة حتى الآن: {self.impact_nodes}.",
            )

    # stage completions ----------------------------------------------------

    def _ingest_done(self, result: dict[str, Any]) -> None:
        ingested = result.get("ingested") or []
        clauses = 0
        with Session(db_session.get_engine()) as db:
            for row in ingested:
                if row.get("version_id"):
                    clauses += int(db.scalar(
                        select(func.count()).select_from(Clause).where(Clause.version_id == row["version_id"])
                    ) or 0)
        after = embedding_cache.stats_snapshot()
        texts = after["texts"] - self.emb_before.get("texts", 0)
        hits = after["cache_hits"] - self.emb_before.get("cache_hits", 0)
        if texts:
            emb_en = (f"Embeddings: {hits} of {texts} read from the local embedding cache of an earlier "
                      f"identical run, {texts - hits} computed live.")
            emb_ar = (f"المتجهات: {hits} من أصل {texts} قُرئت من الذاكرة المحلية لتشغيل سابق مطابق، "
                      f"و{texts - hits} حُسبت مباشرة.")
        elif ingested:
            emb_en, emb_ar = "Embeddings: all computed live by the embedding model.", "المتجهات: حُسبت جميعها مباشرة بواسطة نموذج التضمين."
        else:
            emb_en, emb_ar = "No new document needed indexing.", "لا توجد وثيقة جديدة تحتاج إلى فهرسة."
        TRACKER.stage_done(
            "ingest",
            {"versions_ingested": len(ingested), "clauses_ingested": clauses,
             "embeddings_total": texts, "embeddings_from_cache": hits},
            f"{len(ingested)} version(s) ingested, {clauses} clauses parsed and indexed. {emb_en}",
            f"عدد الإصدارات المُدخلة: {len(ingested)}، وعدد البنود المستخرجة والمفهرسة: {clauses}. {emb_ar}",
        )

    def _aligned(self, d: dict[str, Any]) -> None:
        self.aligned = d
        mc = d["match_counts"]
        self.classify_llm_before = llm_cache.stats_snapshot()
        TRACKER.stage_done(
            "align",
            {"clauses_old": d["from_clauses"], "clauses_new": d["to_clauses"],
             "exact_id": mc.get("exact_id", 0), "renumbered_candidate": mc.get("renumbered_candidate", 0),
             "new": mc.get("new", 0), "withdrawn": mc.get("withdrawn", 0),
             "identical_skipped": d["identical"], "to_classify": d["to_classify"]},
            f"Exact ID matches: {mc.get('exact_id', 0)}, renumbered: {mc.get('renumbered_candidate', 0)}, "
            f"new: {mc.get('new', 0)}, withdrawn: {mc.get('withdrawn', 0)}. "
            f"Identical clauses skipped: {d['identical']}. To classify: {d['to_classify']}.",
            f"المطابقة بالرقم: {mc.get('exact_id', 0)}، معاد ترقيمها: {mc.get('renumbered_candidate', 0)}، "
            f"جديدة: {mc.get('new', 0)}، ملغاة: {mc.get('withdrawn', 0)}. "
            f"البنود المتطابقة (تم تجاوزها): {d['identical']}. المطلوب تصنيفها: {d['to_classify']}.",
        )
        TRACKER.stage_start(
            "classify", f"Classifying {d['to_classify']} changes with the model.",
            f"جارٍ تصنيف {d['to_classify']} تغييرًا بواسطة النموذج.",
        )

    def _diff_done(self, result: dict[str, Any]) -> None:
        pairs = result.get("diffed_pairs") or []
        if self.aligned is None:  # nothing was pending to diff
            TRACKER.stage_done("align", {}, "No version pair was pending, nothing to match.",
                               "لا يوجد زوج من الإصدارات بانتظار المطابقة.", pace=False)
        changes = sum(p.get("change_count", 0) for p in pairs)
        material = sum(p.get("material_count", 0) for p in pairs)
        calls, hits = llm_cache.stats_delta(
            self.classify_llm_before if self.classify_llm_before is not None else llm_cache.stats_snapshot(),
            llm_cache.stats_snapshot(), "classify")
        live = calls - hits
        self.summary.update(changes_classified=changes, material_changes=material)
        TRACKER.stage_done(
            "classify",
            {"changes_classified": changes, "material_changes": material,
             "llm_calls": calls, "llm_cache_hits": hits, "llm_live_calls": live},
            f"Classified {changes} changes, {material} material. "
            f"{hits} of {calls} answered from the local cache of an earlier identical run, {live} answered live by the model.",
            f"تم تصنيف {changes} تغييرًا، منها {material} جوهريًا. "
            f"{hits} من أصل {calls} أُجيب عنها من الذاكرة المحلية لتشغيل سابق مطابق، و{live} أجاب عنها النموذج مباشرة.",
        )

    def _impact_done(self, result: dict[str, Any]) -> None:
        impacted = result.get("impacted") or []
        with_impact = sum(1 for r in impacted if r["impact_count"] > 0)
        nodes = sum(r["impact_count"] for r in impacted)
        calls, hits = llm_cache.stats_delta(
            self.impact_llm_before if self.impact_llm_before is not None else llm_cache.stats_snapshot(),
            llm_cache.stats_snapshot(), "impact")
        live = calls - hits
        self.summary.update(impacted_nodes=nodes, changes_with_impact=with_impact)
        TRACKER.stage_done(
            "impact",
            {"material_changes": len(impacted), "changes_with_impact": with_impact, "impacted_nodes": nodes,
             "llm_calls": calls, "llm_cache_hits": hits, "llm_live_calls": live},
            f"{len(impacted)} material changes traced, {with_impact} reach the company's control mappings, "
            f"{nodes} impacted nodes. {hits} of {calls} impact notes answered from the local cache of an earlier "
            f"identical run, {live} written live by the model.",
            f"تم تتبع {len(impacted)} تغييرًا جوهريًا، منها {with_impact} يمس ضوابط الشركة المرتبطة، "
            f"وعدد العناصر المتأثرة: {nodes}. {hits} من أصل {calls} ملاحظة أثر أُجيب عنها من الذاكرة المحلية "
            f"لتشغيل سابق مطابق، و{live} كتبها النموذج مباشرة.",
        )

    def _prioritize_done(self, result: dict[str, Any]) -> None:
        priorities = result.get("priorities") or {}
        bands: dict[str, int] = {}
        for p in priorities.values():
            bands[str(p.get("band"))] = bands.get(str(p.get("band")), 0) + 1
        text_en = ", ".join(f"{k}: {v}" for k, v in sorted(bands.items())) or "none"
        TRACKER.stage_done(
            "prioritize", {"changes_scored": len(priorities), "bands": bands},
            f"{len(priorities)} changes scored by the deterministic formula ({text_en}).",
            f"تم تقييم {len(priorities)} تغييرًا بالمعادلة المحددة سلفًا (المستويات: {text_en}).",
        )

    def _policy_done(self, result: dict[str, Any]) -> None:
        ids = result.get("action_ids") or []
        by_level: dict[str, int] = {}
        if ids:
            with Session(db_session.get_engine()) as db:
                for level, n in db.execute(
                    select(Action.level, func.count()).where(Action.id.in_(ids)).group_by(Action.level)
                ):
                    by_level[level] = int(n)
        self.summary.update(actions_created=len(ids), actions_by_level=by_level)
        text_en = ", ".join(f"{k}: {v}" for k, v in sorted(by_level.items())) or "none"
        TRACKER.stage_done(
            "policy", {"actions_created": len(ids), "by_level": by_level},
            f"{len(ids)} actions created by the automation policy ({text_en}).",
            f"تم إنشاء {len(ids)} إجراءً وفق سياسة الأتمتة (حسب المستوى: {text_en}).",
        )

    def _auto_done(self, result: dict[str, Any]) -> None:
        n = len(result.get("auto_executed_action_ids") or [])
        self.summary["auto_executed"] = n
        TRACKER.stage_done(
            "auto_execute", {"auto_executed": n},
            f"{n} safe actions closed automatically. Recorded in the database only: no external system was called.",
            f"تم إغلاق {n} إجراءً آمنًا تلقائيًا. سُجّل ذلك في قاعدة البيانات فقط دون استدعاء أي نظام خارجي.",
        )

    def _review_done(self, result: dict[str, Any], interrupts: list[Any]) -> None:
        awaiting = 0
        for it in interrupts:
            value = it.get("value") if isinstance(it, dict) else getattr(it, "value", None)
            awaiting = max(awaiting, len((value or {}).get("awaiting", [])))
        self.awaiting = awaiting
        self.summary["awaiting_review"] = awaiting
        TRACKER.stage_done(
            "review", {"awaiting_review": awaiting},
            f"{awaiting} actions are waiting for a human decision (approve, dismiss or delegate).",
            f"عدد الإجراءات المنتظرة قرار المراجع البشري: {awaiting} (اعتماد أو رفض أو إسناد).",
            pace=False,
        )

    # end of run -----------------------------------------------------------

    def finish(self, paused: bool) -> None:
        after = llm_cache.stats_snapshot()
        calls = sum(after.get(k, {}).get("calls", 0) - self.llm_all_before.get(k, {}).get("calls", 0)
                    for k in ("classify", "impact"))
        hits = sum(after.get(k, {}).get("cache_hits", 0) - self.llm_all_before.get(k, {}).get("cache_hits", 0)
                   for k in ("classify", "impact"))
        pacing = TRACKER.pacing_ms_total
        self.summary.update(llm_calls=calls, llm_cache_hits=hits, llm_live_calls=calls - hits)
        if calls:
            cache_en = (f" {hits} of {calls} model answers in this run came from the local cache of an earlier "
                        f"identical run; {calls - hits} were produced live.")
            cache_ar = (f" {hits} من أصل {calls} إجابة للنموذج في هذا التشغيل جاءت من الذاكرة المحلية لتشغيل سابق "
                        f"مطابق، و{calls - hits} أُنتجت مباشرة.")
        else:
            cache_en, cache_ar = "", ""
        pace_en = f" A {settings.demo_stage_pacing_ms} ms pause between stages is a demo setting." if pacing else ""
        pace_ar = f" الإيقاف القصير بين الخطوات ({settings.demo_stage_pacing_ms} مللي ثانية) إعداد خاص بالعرض." if pacing else ""
        TRACKER.set_note(
            C.SIMULATED_PORTAL_NOTE_EN + cache_en + pace_en,
            C.SIMULATED_PORTAL_NOTE_AR + cache_ar + pace_ar,
        )
        TRACKER.finish("awaiting_review" if paused else "completed", self.summary)
