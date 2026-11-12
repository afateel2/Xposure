"use client";

import { Bi } from "@/components/Bi";
import { Badge, Card, Icon, StatCard, Building2, ClipboardCheck, ShieldCheck } from "@/components/ui";
import { Bot, CircleCheck, Hourglass, MapPin } from "lucide-react";
import type { CompanyNodes, CompanyOverview, NodeStatus } from "@/lib/types-company";

const POSTURE: { status: NodeStatus; tone: "warning" | "info" | "success" | "default"; en: string; ar: string; icon: typeof Bot }[] = [
  { status: "action_required", tone: "warning", en: "Action needed", ar: "يتطلب إجراءً", icon: ClipboardCheck },
  { status: "assigned", tone: "info", en: "Awaiting confirmation", ar: "بانتظار التأكيد", icon: Hourglass },
  { status: "updated_by_agent", tone: "success", en: "Updated by agent", ar: "عُدِّل بواسطة الوكيل", icon: Bot },
  { status: "up_to_date", tone: "default", en: "Up to date", ar: "محدّث", icon: CircleCheck },
];

/**
 * Company card plus the posture counts. The counts are plain numbers of
 * nodes per derived state. No compliance score is computed on purpose: a
 * single percentage would look more certain than the data is.
 */
export function CompanyHeader({ company, nodes }: { company: CompanyOverview; nodes: CompanyNodes | null }) {
  const p = company.profile;
  const followed = company.applied_regulation ?? p.applied_regulation;
  const others = company.known_regulation_versions.filter((v) => v !== followed);

  return (
    <>
      <Card headless className="fac-company">
        <div className="fac-company-grid">
          <div className="fac-company-id">
            <span className="fac-company-icon" aria-hidden="true"><Icon icon={Building2} size={26} /></span>
            <div>
              <h2 className="fac-company-name"><Bi en={p.name_en} ar={p.name_ar} /></h2>
              <p className="fac-company-sector"><Bi en={p.sector_en} ar={p.sector_ar} /></p>
              <ul className="fac-company-facts">
                <li><Icon icon={MapPin} size={14} /><Bi en={p.location_en} ar={p.location_ar} /></li>
                <li><Bi en="Site" ar="الموقع" />: <bdi>{p.site}</bdi></li>
                {p.employees != null && <li><bdi className="tabular">{p.employees}</bdi> <Bi en="employees" ar="موظفًا" /></li>}
              </ul>
            </div>
          </div>
          <div className="fac-company-reg">
            <div className="fac-company-reg-label"><Icon icon={ShieldCheck} size={15} /><Bi en="Regulation currently followed" ar="التنظيم المطبَّق حاليًا" /></div>
            <div className="fac-company-reg-value"><bdi className="mono">{followed}</bdi></div>
            {others.length > 0 && (
              <div className="fac-company-reg-others">
                <Bi en="Known to the agent, not yet applied:" ar="معروف للوكيل ولم يُطبَّق بعد:" />{" "}
                {others.map((v) => <Badge key={v} variant="new"><bdi className="mono">{v}</bdi></Badge>)}
              </div>
            )}
          </div>
        </div>
      </Card>

      <h2 className="xp-section-title fac-posture-title"><Bi en="Where the company stands" ar="موقف الشركة الحالي" /></h2>
      <div className="xp-grid cols-4 fac-posture">
        {POSTURE.map((s) => {
          const count = nodes?.counts_by_status[s.status] ?? 0;
          return (
            <StatCard
              key={s.status}
              tone={count > 0 ? s.tone : "default"}
              label={<Bi en={s.en} ar={s.ar} />}
              value={nodes ? count : "-"}
              trend={<Bi en="company nodes" ar="عنصرًا في الشركة" />}
              icon={<Icon icon={s.icon} size={16} />}
            />
          );
        })}
      </div>
      <p className="fac-posture-note">
        <Bi
          en={<>Counts of company nodes by state. The agent does not compute a compliance score: <bdi>{company.counts.open_actions}</bdi> actions are waiting for a decision and <bdi>{company.counts.assigned_actions}</bdi> for confirmation.</>}
          ar={<>أعداد عناصر الشركة حسب حالتها. لا يحسب الوكيل درجة امتثال: بانتظار القرار <bdi>{company.counts.open_actions}</bdi> إجراءً، وبانتظار التأكيد <bdi>{company.counts.assigned_actions}</bdi>.</>}
        />
      </p>
    </>
  );
}
