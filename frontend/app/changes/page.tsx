"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { X } from "lucide-react";
import { ChangeRow } from "@/components/ChangeRow";
import { Bi } from "@/components/Bi";
import { Button, BrandMotif, Card, Checkbox, Icon, Input, PageHeader, Segmented } from "@/components/ui";
import { getChange, getChanges } from "@/lib/api";
import { CHANGE_TYPE_LABEL } from "@/lib/labels";
import { t, useLang } from "@/lib/lang";
import { needsAttention } from "@/lib/review-queue";
import { parseTs } from "@/lib/time";
import { getStoredWhoAmI, setStoredWhoAmI } from "@/lib/whoami";
import type { ChangeDetailOut, ChangeSummaryOut, PriorityBand } from "@/lib/types";

type BandFilter = "all" | PriorityBand;

const BAND_OPTIONS: { value: BandFilter; en: string; ar: string }[] = [
  { value: "all", en: "All", ar: "الكل" },
  { value: "critical", en: "Critical", ar: "حرج" },
  { value: "high", en: "High", ar: "عالي" },
  { value: "medium", en: "Medium", ar: "متوسط" },
  { value: "low", en: "Low", ar: "منخفض" },
];

const LAST_SEEN_KEY = "xposure_changes_last_seen";
const BASELINE_KEY = "xposure_changes_baseline";

function matchesQuery(change: ChangeSummaryOut, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (needle === "") return true;
  const typeLabel = change.change_type ? CHANGE_TYPE_LABEL[change.change_type] : null;
  const haystack = [
    String(change.id),
    change.clause_ref ?? "",
    change.old_clause_id ?? "",
    change.new_clause_id ?? "",
    change.summary_en,
    change.summary_ar,
    change.regulator.code,
    change.regulator.name_en,
    change.regulator.name_ar,
    change.regulation.code,
    change.regulation.title_en,
    change.regulation.title_ar,
    typeLabel?.en ?? "",
    typeLabel?.ar ?? "",
    ...change.assigned_to,
  ]
    .join(" \n ")
    .toLowerCase();
  return haystack.includes(needle);
}

/**
 * "New since your last visit": the previous visit time lives in localStorage
 * (try/catch, it can be blocked). The baseline is pinned in sessionStorage so
 * a refresh in the same tab keeps the highlight, while a later visit compares
 * against the time this one started.
 */
function readBaseline(): number | null {
  try {
    const pinned = sessionStorage.getItem(BASELINE_KEY);
    if (pinned) return parseTs(pinned);
    const previous = localStorage.getItem(LAST_SEEN_KEY);
    if (previous) sessionStorage.setItem(BASELINE_KEY, previous);
    localStorage.setItem(LAST_SEEN_KEY, new Date().toISOString());
    return previous ? parseTs(previous) : null;
  } catch {
    return null;
  }
}

function ChangesView() {
  const lang = useLang();
  const router = useRouter();
  const searchParams = useSearchParams();
  const q = searchParams.get("q") ?? "";
  const [changes, setChanges] = useState<ChangeSummaryOut[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [bandFilter, setBandFilter] = useState<BandFilter>("all");
  const [showResolved, setShowResolved] = useState(false);
  const [assignedToMeOnly, setAssignedToMeOnly] = useState(false);
  const [whoAmI, setWhoAmI] = useState("");
  const [baseline, setBaseline] = useState<number | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [detailCache, setDetailCache] = useState<Record<number, ChangeDetailOut>>({});
  const [detailErrors, setDetailErrors] = useState<Record<number, string>>({});

  const load = useCallback(() => {
    setLoadError(null);
    setChanges(null);
    getChanges({ materialOnly: true })
      .then(setChanges)
      .catch((err) => setLoadError(err instanceof Error ? err.message : String(err)));
  }, []);

  useEffect(() => {
    setWhoAmI(getStoredWhoAmI());
    setBaseline(readBaseline());
    load();
  }, [load]);

  function toggleRow(id: number) {
    const next = expandedId === id ? null : id;
    setExpandedId(next);
    if (next !== null && !detailCache[next]) {
      getChange(next)
        .then((detail) => setDetailCache((prev) => ({ ...prev, [next]: detail })))
        .catch((err) =>
          setDetailErrors((prev) => ({ ...prev, [next]: err instanceof Error ? err.message : String(err) })),
        );
    }
  }

  function saveWhoAmI(value: string) {
    setWhoAmI(value);
    setStoredWhoAmI(value);
  }

  const searched = useMemo(() => (changes ?? []).filter((c) => matchesQuery(c, q)), [changes, q]);
  const triaged = useMemo(() => searched.filter((c) => showResolved || needsAttention(c)), [searched, showResolved]);
  const hiddenCount = searched.length - searched.filter(needsAttention).length;

  const bandCounts = useMemo(() => {
    const counts: Record<BandFilter, number> = { all: triaged.length, critical: 0, high: 0, medium: 0, low: 0 };
    for (const c of triaged) counts[c.priority_band]++;
    return counts;
  }, [triaged]);

  const visible = triaged.filter((c) => {
    if (bandFilter !== "all" && c.priority_band !== bandFilter) return false;
    if (assignedToMeOnly && whoAmI.trim() !== "" && !c.assigned_to.includes(whoAmI.trim())) return false;
    return true;
  });

  const isNew = (c: ChangeSummaryOut) => {
    if (baseline == null) return false;
    const created = parseTs(c.created_at);
    return created != null && created > baseline;
  };
  const newCount = visible.filter(isNew).length;

  const regulationPath = useMemo(() => {
    if (!changes || changes.length === 0) return null;
    const first = changes[0];
    return `${first.regulator.code.toUpperCase()} ${first.regulation.code.toUpperCase()}`;
  }, [changes]);

  return (
    <main>
      <PageHeader
        title={<Bi en="Material regulatory changes" ar="التغييرات التنظيمية الجوهرية" />}
        subtitle={
          regulationPath ? (
            <>
              <bdi>{regulationPath}</bdi>
              {" · "}
              <Bi en="Changes that still need a decision come first." ar="تظهر أولًا التغييرات التي ما زالت تحتاج إلى قرار." />
            </>
          ) : undefined
        }
      />

      <div className="chg-toolbar">
        <Segmented<BandFilter>
          value={bandFilter}
          onChange={setBandFilter}
          ariaLabel={t(lang, "Filter by priority", "التصفية حسب الأولوية")}
          options={BAND_OPTIONS.map((o) => ({
            value: o.value,
            label: (
              <>
                <Bi en={o.en} ar={o.ar} /> <span className="chg-seg-count tabular">{bandCounts[o.value]}</span>
              </>
            ),
          }))}
        />
        <div className="chg-toolbar-toggles">
          <Checkbox checked={showResolved} onChange={(e) => setShowResolved(e.target.checked)}>
            <Bi
              en={`Show resolved and dismissed too (${hiddenCount} hidden)`}
              ar={`إظهار المُنجَز والمُتجاهَل أيضًا (${hiddenCount} مخفي)`}
            />
          </Checkbox>
          <Checkbox checked={assignedToMeOnly} onChange={(e) => setAssignedToMeOnly(e.target.checked)} disabled={whoAmI.trim() === ""}>
            <Bi en="Assigned to me" ar="مُسنَد إليّ" />
          </Checkbox>
        </div>
        <Input
          className="chg-whoami"
          placeholder={t(lang, "Who am I? (for the filter)", "من أنا؟ (لتفعيل الفلتر)")}
          aria-label={t(lang, "Who am I? Used by the assigned to me filter", "من أنا؟ يُستخدم في فلتر المُسنَد إليّ")}
          value={whoAmI}
          onChange={(e) => saveWhoAmI(e.target.value)}
        />
      </div>

      {q.trim() !== "" && (
        <div className="chg-query" role="status">
          <span>
            <Bi en="Search results for" ar="نتائج البحث عن" /> <b><bdi>{q}</bdi></b>
            {" · "}
            <span className="tabular"><Bi en={`${visible.length} shown`} ar={`${visible.length} معروض`} /></span>
          </span>
          <Button variant="link" size="sm" icon={<Icon icon={X} size={14} />} onClick={() => router.replace("/changes")}>
            <Bi en="Clear search" ar="مسح البحث" />
          </Button>
        </div>
      )}

      {newCount > 0 && (
        <p className="chg-new-note" role="status">
          <Bi
            en={`${newCount} new since your last visit, highlighted below.`}
            ar={`${newCount} جديد منذ زيارتك الأخيرة، مميّز أدناه.`}
          />
        </p>
      )}

      {loadError && (
        <Card className="xp-error-card" headless>
          <p role="alert">{loadError}</p>
          <div style={{ marginBlockStart: 10 }}>
            <Button variant="secondary" size="sm" onClick={load}><Bi en="Try again" ar="إعادة المحاولة" /></Button>
          </div>
        </Card>
      )}
      {!loadError && changes === null && <BrandMotif variant="spinner" title={<Bi en="Loading changes..." ar="جارٍ تحميل التغييرات..." />} />}
      {!loadError && changes !== null && visible.length === 0 && (
        <BrandMotif
          variant="empty"
          title={<Bi en="No changes match this view" ar="لا توجد تغييرات مطابقة لهذا العرض" />}
          hint={
            changes.length === 0 ? (
              <Bi en="No changes have been detected yet. Run a scan from the dashboard to compare the latest regulation versions." ar="لم تُرصد أي تغييرات بعد. شغّل فحصًا من لوحة التحكم لمقارنة أحدث إصدارات الأنظمة." />
            ) : (
              <Bi en="Try another priority, search term, or show resolved items." ar="جرّب أولوية أو عبارة بحث أخرى، أو أظهر العناصر المُنجَزة." />
            )
          }
        />
      )}

      {!loadError && visible.length > 0 && (
        <ul className="chg-list">
          {visible.map((change) => (
            <ChangeRow
              key={change.id}
              change={change}
              expanded={expandedId === change.id}
              onToggle={() => toggleRow(change.id)}
              detail={detailCache[change.id] ?? null}
              detailError={detailErrors[change.id] ?? null}
              isNew={isNew(change)}
            />
          ))}
        </ul>
      )}

      <p className="chg-foot-note">
        <Bi
          en="Priority is a deterministic score (app/priority.py): what kind of change it is, how much of the organization it reaches, and how close its deadline is. It is recomputed live from real classified changes, org-graph impact and the automation policy. This list defaults to changes that still need a decision; resolved and dismissed items stay out of the way until you ask for them."
          ar="الأولوية درجة حتمية (app/priority.py): نوع التغيير، ومدى اتساع تأثيره في المؤسسة، وقرب موعده. تُحسب مباشرةً من تصنيفات حقيقية وتأثير فعلي على مخطط المؤسسة وسياسة الأتمتة. تعرض هذه القائمة افتراضيًا التغييرات التي ما زالت بحاجة إلى قرار، بينما تبقى العناصر المُنجزة والمُتجاهَلة بعيدًا عن الطريق حتى تطلبها."
        />
      </p>
    </main>
  );
}

export default function ChangesPage() {
  return (
    <Suspense fallback={<main><BrandMotif variant="spinner" title={<Bi en="Loading changes..." ar="جارٍ تحميل التغييرات..." />} /></main>}>
      <ChangesView />
    </Suspense>
  );
}
