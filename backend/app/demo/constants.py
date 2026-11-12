"""Shared constants for the demo pipeline."""

from __future__ import annotations

from dataclasses import dataclass

# The demo's starting point: one regulator, one regulation, one version.
BASELINE_REGULATOR = "nca"
BASELINE_REGULATION = "ecc"
BASELINE_VERSION = "1-2018"
NEW_VERSION = "2-2024"

# Audit events this package writes (the pipeline's own events are unchanged).
EVT_SCAN_REQUESTED = "scan_requested"
EVT_STAGE_STARTED = "stage_started"
EVT_STAGE_COMPLETED = "stage_completed"
EVT_SCAN_COMPLETED = "scan_completed"
EVT_SCAN_FAILED = "scan_failed"
EVT_DEMO_RESET = "demo_reset"
RUN_EVENTS = (
    EVT_SCAN_REQUESTED,
    EVT_STAGE_STARTED,
    EVT_STAGE_COMPLETED,
    EVT_SCAN_COMPLETED,
    EVT_SCAN_FAILED,
)

ACTOR_USER = "user:demo"
ACTOR_RUNNER = "agent:demo_runner"

RUN_STATUSES = ("idle", "running", "awaiting_review", "completed", "failed")
STAGE_STATUSES = ("pending", "running", "done", "failed")


@dataclass(frozen=True)
class StageDef:
    key: str
    label_en: str
    label_ar: str


#: The visible steps of a scan, in order. `align` and `classify` are both
#: produced by the graph's `diff` node; `portal` and `fetch` run before the
#: graph (they replay the regulator portal from the local mirror folder).
STAGES: tuple[StageDef, ...] = (
    StageDef("portal", "Checking the regulator portal", "فحص بوابة الجهة التنظيمية"),
    StageDef("fetch", "Fetching the new document", "جلب الوثيقة الجديدة"),
    StageDef("ingest", "Reading and indexing the document", "قراءة الوثيقة وفهرستها"),
    StageDef("align", "Matching clauses between versions", "مطابقة البنود بين الإصدارين"),
    StageDef("classify", "Classifying each change", "تصنيف كل تغيير"),
    StageDef("impact", "Tracing impact through the company", "تتبع الأثر على الشركة"),
    StageDef("prioritize", "Prioritizing by risk", "ترتيب الأولويات حسب المخاطر"),
    StageDef("policy", "Applying the automation policy", "تطبيق سياسة الأتمتة"),
    StageDef("auto_execute", "Executing safe actions automatically", "تنفيذ الإجراءات الآمنة تلقائيًا"),
    StageDef("review", "Ready for human review", "جاهز للمراجعة البشرية"),
)
STAGE_KEYS = tuple(s.key for s in STAGES)
STAGE_BY_KEY = {s.key: s for s in STAGES}

#: Graph node name -> the stage that starts when that node starts.
NODE_STARTS_STAGE = {
    "check_sources": "ingest",
    "diff": "align",
    "impact": "impact",
    "prioritize": "prioritize",
    "apply_policy": "policy",
    "auto_execute": "auto_execute",
    "human_review": "review",
}

SIMULATED_PORTAL_NOTE_EN = (
    "The guided demo replays the regulator portal from a local mirror folder "
    "so a scan is fast and repeatable. "
    "A live check against the regulator's own page is available on the Sources screen."
)
SIMULATED_PORTAL_NOTE_AR = (
    "يعيد العرض الإرشادي تشغيل بوابة الجهة التنظيمية من مجلد محلي مطابق لها "
    "ليكون الفحص سريعًا وقابلًا للتكرار. "
    "ويتوفر فحص مباشر لصفحة الجهة التنظيمية نفسها من شاشة المصادر."
)
