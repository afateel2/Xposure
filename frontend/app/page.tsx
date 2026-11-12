"use client";

import { useEffect, useRef } from "react";
import { CalendarClock, FileText, Globe, LayoutGrid, ListChecks, Radio, Target, TriangleAlert } from "lucide-react";
import { Bi } from "@/components/Bi";
import { ActivityFeed } from "@/components/ActivityFeed";
import { RelTime } from "@/components/RelTime";
import { AttentionList } from "@/components/dashboard/AttentionList";
import { DeadlineTimeline } from "@/components/dashboard/DeadlineTimeline";
import { ImpactGrid } from "@/components/dashboard/ImpactGrid";
import { KpiRow } from "@/components/dashboard/KpiRow";
import { NewSinceVisit } from "@/components/dashboard/NewSinceVisit";
import { PriorityMatrix } from "@/components/dashboard/PriorityMatrix";
import { SourceCards } from "@/components/dashboard/SourceCards";
import { StatusStrip } from "@/components/dashboard/StatusStrip";
import { BrandMotif, Button, Card, Icon, PageHeader, buttonClass } from "@/components/ui";
import { getChanges } from "@/lib/api";
import { ApiError, getAgentState, getOverview } from "@/lib/api-visibility";
import { usePoll } from "@/lib/use-poll";

export default function DashboardPage() {
  const scanning = useRef(false);

  // Agent state: every 5 s while scanning, otherwise every 30 s (paused while the tab is hidden).
  const agent = usePoll(getAgentState, (d) => (d?.state === "scanning" ? 5_000 : 30_000));
  // Overview follows the agent: quicker while a scan runs.
  const overview = usePoll(getOverview, () => (scanning.current ? 8_000 : 30_000));
  // The open changes, for the reach/severity grid and the deadline view. Same cadence as the overview.
  const changes = usePoll(() => getChanges({ materialOnly: true }), () => (scanning.current ? 8_000 : 30_000));

  const state = agent.data?.state ?? null;
  useEffect(() => {
    scanning.current = state === "scanning";
  }, [state]);
  const reloadOverview = overview.reload;
  const prevState = useRef<string | null>(null);
  useEffect(() => {
    // A state change (scan finished, review ready) means the numbers moved: refresh now.
    if (prevState.current !== null && prevState.current !== state) reloadOverview();
    prevState.current = state;
  }, [state, reloadOverview]);

  const ov = overview.data;
  const overviewMissing = !ov && !overview.loading && overview.error instanceof ApiError && overview.error.status === 404;
  const refreshKey = ov ? `${ov.review_queue.total}:${ov.review_queue.critical}:${ov.review_queue.pending_actions}` : "none";
  const issues = ov ? ov.monitoring.file_issues.conflict + ov.monitoring.file_issues.unrecognized : 0;

  return (
    <main className="dash">
      <PageHeader
        title={<Bi en="Dashboard" ar="لوحة التحكم" />}
        subtitle={<Bi en="What the agent is doing, how fresh the data is, and what needs a decision." ar="ما يفعله الوكيل الآن، ومدى حداثة البيانات، وما يحتاج إلى قرار." />}
        actions={
          <>
            {/* /api/exports/summary is a file download served by the proxy, not a page: a plain anchor is correct. */}
            <a className={buttonClass({ variant: "secondary" })} href="/api/exports/summary" download>
              <Icon icon={FileText} size={16} />
              <Bi en="Export summary PDF" ar="تصدير ملخص PDF" />
            </a>
            <Button variant="primary" href="/changes" icon={<Icon icon={ListChecks} size={16} />}>
              <Bi en="Review changes" ar="مراجعة التغييرات" />
            </Button>
          </>
        }
      />

      <NewSinceVisit />

      {overviewMissing ? (
        <Card>
          <BrandMotif
            title={<Bi en="The overview is not available" ar="نظرة عامة غير متاحة" />}
            hint={<Bi en="The backend does not serve /overview yet. Nothing is shown rather than guessing." ar="الخادم لا يوفّر بيانات النظرة العامة بعد، ولذلك لا نعرض شيئًا بدل التخمين." />}
          />
        </Card>
      ) : (
        <>
          <StatusStrip agent={agent.data} agentUnavailable={!agent.data && !!agent.error} overview={ov} />

          {overview.error != null && ov && (
            <p className="dash-stale" role="status">
              <Icon icon={TriangleAlert} size={14} />
              <span>
                <Bi en="Could not refresh the numbers. Showing the last update, " ar="تعذّر تحديث الأرقام. المعروض هو آخر تحديث، " />
                <RelTime iso={overview.updatedAt ? new Date(overview.updatedAt).toISOString() : null} />
              </span>
            </p>
          )}
          {issues > 0 && ov && (
            <p className="dash-stale" role="status">
              <Icon icon={TriangleAlert} size={14} />
              <Bi
                en={`${ov.monitoring.file_issues.conflict} source file conflicts and ${ov.monitoring.file_issues.unrecognized} unrecognised files need a human look.`}
                ar={`${ov.monitoring.file_issues.conflict} تعارضات في ملفات المصادر و${ov.monitoring.file_issues.unrecognized} ملفات غير معروفة تحتاج إلى مراجعة بشرية.`}
              />
            </p>
          )}

          <KpiRow overview={ov} />

          <div className="dash-grid">
            <div className="dash-col">
            <Card
              as="section"
              title={<Bi en="Regulatory sources" ar="المصادر التنظيمية" />}
              icon={<Icon icon={Globe} size={18} />}
              actions={<Button variant="link" size="sm" href="/sources"><Bi en="Manage" ar="إدارة" /></Button>}
            >
              <SourceCards sources={ov?.sources ?? null} />
            </Card>

            <Card
              as="section"
              title={<Bi en="Needs your attention" ar="يتطلب انتباهك" />}
              icon={<Icon icon={TriangleAlert} size={18} />}
              actions={<Button variant="link" size="sm" href="/changes"><Bi en="All changes" ar="كل التغييرات" /></Button>}
            >
              <AttentionList refreshKey={refreshKey} />
            </Card>
            </div>

            <div className="dash-col">
            <Card
              as="section"
              title={<Bi en="Live activity" ar="النشاط المباشر" />}
              icon={<Icon icon={Radio} size={18} />}
              actions={<span className="dash-live"><i aria-hidden="true" /><Bi en="Live" ar="مباشر" /></span>}
            >
              <ActivityFeed limit={10} compact />
            </Card>

            <Card as="section" title={<Bi en="Priority matrix" ar="مصفوفة الأولويات" />} icon={<Icon icon={Target} size={18} />}>
              <PriorityMatrix matrix={ov?.priority_matrix ?? null} />
            </Card>
            </div>
          </div>

          <div className="dash-grid dash-grid-even">
            <Card as="section" title={<Bi en="Where the open work is" ar="أين يقع العمل المفتوح" />} icon={<Icon icon={LayoutGrid} size={18} />}>
              <ImpactGrid changes={changes.data} />
            </Card>
            <Card as="section" title={<Bi en="Deadlines" ar="المواعيد" />} icon={<Icon icon={CalendarClock} size={18} />}>
              <DeadlineTimeline changes={changes.data} />
            </Card>
          </div>

          <footer className="dash-foot">
            <p>
              {ov ? (
                <>
                  <Bi en="Data as of " ar="البيانات حتى " />
                  <RelTime iso={ov.generated_at} />
                  <span className="dash-foot-sep" aria-hidden="true">{"·"}</span>
                </>
              ) : null}
              <Bi
                en="Demo data: Eastern Industrial Company is a fictional company. Regulator documents are read from a local copy, not from live websites."
                ar="بيانات توضيحية: الشركة الصناعية الشرقية شركة افتراضية، وتُقرأ وثائق الجهات التنظيمية من نسخة محلية لا من مواقعها المباشرة."
              />
            </p>
          </footer>
        </>
      )}
    </main>
  );
}
