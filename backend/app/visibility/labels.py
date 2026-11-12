"""
Bilingual vocabulary for the visibility endpoints.

English/Arabic pairs mirror frontend/lib/labels.ts wherever a label already
exists there (action types, priority bands, change types), so a string
produced by the backend reads the same as one rendered by the UI.

Arabic register: professional Saudi regulatory Arabic, no em dashes. Latin
identifiers (clause numbers, file paths, regulator codes, org node names)
are wrapped in Unicode bidi isolates by isolate() so they render correctly
inside a right-to-left sentence without needing markup.
"""

FSI = "⁨"  # first strong isolate
PDI = "⁩"  # pop directional isolate


def isolate(text: object) -> str:
    """Wrap a Latin/numeric token so it keeps its own direction inside Arabic text."""
    return f"{FSI}{text}{PDI}"


def clean(text: str | None) -> str | None:
    """Data carried into a sentence (org node names, clause titles) may contain
    the long dash character; the product never shows it, so it becomes a plain hyphen."""
    if text is None:
        return None
    return text.replace(chr(0x2014), "-").replace(chr(0x2013), "-")


def trunc(text: object, limit: int = 220) -> str:
    value = " ".join(str(text).split())
    return value if len(value) <= limit else value[: limit - 3].rstrip() + "..."


# ── Arabic counting ───────────────────────────────────────────────────────
# Forms are (one, two, few 3-10, many 11+) and are the OBLIQUE forms, meant
# to be the object of a verbal noun or a preposition: "تم إنشاء 43 إجراءً",
# "تم إنشاء إجراءين". The dual is therefore the -ين form and the 11+ form is
# the accusative singular (tamyiz).
ACTION = ("إجراء واحد", "إجراءين", "إجراءات", "إجراءً")
CHANGE = ("تغيير واحد", "تغييرين", "تغييرات", "تغييرًا")
NODE = ("عقدة واحدة", "عقدتين", "عقد", "عقدةً")
DOCUMENT = ("وثيقة واحدة", "وثيقتين", "وثائق", "وثيقةً")
VERSION = ("إصدار واحد", "إصدارين", "إصدارات", "إصدارًا")
NOTIFICATION = ("إشعار واحد", "إشعارين", "إشعارات", "إشعارًا")
PAIR = ("زوج واحد", "زوجين", "أزواج", "زوجًا")


def ar_count(n: int, forms: tuple[str, str, str, str]) -> str:
    """Number plus noun with Arabic numeral-noun agreement."""
    if n == 1:
        return forms[0]
    if n == 2:
        return forms[1]
    if 3 <= n <= 10:
        return f"{n} {forms[2]}"
    return f"{n} {forms[3]}"


def en_count(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


# ── Vocabulary ────────────────────────────────────────────────────────────
ACTION_TYPE_LABEL: dict[str, tuple[str, str]] = {
    "update_policy": ("Update policy", "تحديث سياسة"),
    "update_procedure": ("Update procedure", "تحديث إجراء"),
    "technical_change": ("Technical change", "تغيير تقني"),
    "collect_evidence": ("Collect evidence", "جمع أدلة"),
    "reassess_control": ("Reassess control", "إعادة تقييم الضابط"),
    "notify_owner": ("Notify owner", "إشعار المالك"),
    "request_license_review": ("Request license review", "طلب مراجعة ترخيص"),
}

ACTION_LEVEL_LABEL: dict[str, tuple[str, str]] = {
    "notify_only": ("Notify only", "إشعار فقط"),
    "draft_then_approve": ("Draft, then approve", "مسودة ثم اعتماد"),
    "auto_execute": ("Auto-execute", "تنفيذ تلقائي"),
}

ACTION_STATUS_LABEL: dict[str, tuple[str, str]] = {
    "pending": ("Pending review", "بانتظار القرار"),
    "approved": ("Approved", "معتمد"),
    "dismissed": ("Dismissed", "مُتجاهَل"),
    "awaiting_confirmation": ("Awaiting confirmation", "بانتظار تأكيد الإنجاز"),
    "done": ("Done", "منجز"),
}

# Every status an Action can hold, in lifecycle order (used to zero-fill summaries).
ACTION_STATUSES = ("pending", "awaiting_confirmation", "approved", "done", "dismissed")
# Statuses that still need somebody to do something.
OPEN_STATUSES = ("pending", "awaiting_confirmation")
# Statuses that count as resolved for the remediation percentage.
RESOLVED_STATUSES = ("approved", "dismissed", "done")

CHANGE_TYPE_LABEL: dict[str, tuple[str, str]] = {
    "new_obligation": ("New obligation", "التزام جديد"),
    "tightened": ("Tightened", "تشديد"),
    "relaxed": ("Relaxed", "تخفيف"),
    "clarification": ("Clarification", "توضيح"),
    "editorial": ("Editorial", "تحرير"),
    "renumbered": ("Renumbered", "إعادة ترقيم"),
    "withdrawn": ("Withdrawn", "مُلغى"),
}

BAND_LABEL: dict[str, tuple[str, str]] = {
    "critical": ("Critical", "حرج"),
    "high": ("High", "عالي"),
    "medium": ("Medium", "متوسط"),
    "low": ("Low", "منخفض"),
}

# The app scores changes into four bands (priority.py). The dashboard shows
# them under two vocabularies, so both mappings live here in one place:
#   band      review_queue key   priority_matrix key
#   critical  critical           critical
#   high      urgent             quick
#   medium    strategic          strategic
#   low       followup           followup
BAND_TO_REVIEW_KEY = {"critical": "critical", "high": "urgent", "medium": "strategic", "low": "followup"}
BAND_TO_MATRIX_KEY = {"critical": "critical", "high": "quick", "medium": "strategic", "low": "followup"}

MATRIX_LABEL: dict[str, tuple[str, str]] = {
    "critical": ("Critical", "حرج"),
    "quick": ("Quick action", "إجراء سريع"),
    "strategic": ("Strategic", "استراتيجي"),
    "followup": ("Follow-up", "متابعة"),
}

# Pipeline stage keys the demo runner and the LangGraph nodes use.
STAGE_LABEL: dict[str, tuple[str, str]] = {
    "check_sources": ("Checking regulator sources", "فحص مصادر الجهات التنظيمية"),
    "ingest_new": ("Ingesting new versions", "استيعاب الإصدارات الجديدة"),
    "ingest": ("Ingesting new versions", "استيعاب الإصدارات الجديدة"),
    "diff": ("Comparing versions clause by clause", "مقارنة الإصدارات بندًا ببند"),
    "classify": ("Classifying changes", "تصنيف التغييرات"),
    "impact": ("Tracing impact on the company", "تتبع الأثر على المنشأة"),
    "prioritize": ("Prioritizing changes", "ترتيب أولوية التغييرات"),
    "apply_policy": ("Applying the automation policy", "تطبيق سياسة الأتمتة"),
    "policy": ("Applying the automation policy", "تطبيق سياسة الأتمتة"),
    "auto_execute": ("Auto-executing safe actions", "تنفيذ الإجراءات المسموح بأتمتتها"),
    "human_review": ("Waiting for human review", "بانتظار المراجعة البشرية"),
    "deliver": ("Delivering the run summary", "تسليم ملخص التشغيل"),
}


def humanize_event(event: str) -> str:
    """'erp_task_synced' -> 'Erp task synced' (fallback wording for unknown events)."""
    text = event.replace("_", " ").replace(":", ": ").strip()
    return text[:1].upper() + text[1:] if text else "Unknown event"


def action_type_label(action_type: str | None) -> tuple[str, str]:
    if not action_type:
        return ("Action", "إجراء")
    return ACTION_TYPE_LABEL.get(action_type, (humanize_event(action_type), isolate(action_type)))


def status_label(status: str | None) -> tuple[str, str]:
    if not status:
        return ("Unknown", "غير معروف")
    return ACTION_STATUS_LABEL.get(status, (humanize_event(status), isolate(status)))
