"use client";

import { Bi } from "@/components/Bi";
import { Button, CircleCheck, Icon, Info } from "@/components/ui";
import type { DemoRun } from "@/lib/types-demo";
import { num } from "./format";

/**
 * The end-of-scan banner: "Scan complete: N changes need your review" with
 * the link to /changes. Shown only when a run really reached
 * awaiting_review or completed. `changes` is the count of changes that still
 * have a pending action (agent state); when unknown the text says so
 * instead of guessing.
 */
export function RunResult({ run, changes }: { run: DemoRun; changes: number | null }) {
  if (run.status !== "awaiting_review" && run.status !== "completed") return null;
  const summary = run.summary ?? {};
  const nothingToDo = summary.nothing_to_do === true;
  const material = num(summary.material_changes);
  const auto = num(summary.auto_executed);
  const n = changes ?? (run.status === "awaiting_review" ? material : null);

  if (nothingToDo) {
    return (
      <div className="run-result is-info" role="status">
        <Icon icon={Info} size={20} />
        <div className="run-result-body">
          <b><Bi en="Scan complete: no new document was found" ar="اكتمل الفحص: لم يُعثر على وثيقة جديدة" /></b>
          <span><Bi en="Nothing was analysed, so there is nothing new to review." ar="لم يُحلَّل شيء، لذلك لا يوجد جديد للمراجعة." /></span>
        </div>
      </div>
    );
  }

  return (
    <div className="run-result" role="status">
      <Icon icon={CircleCheck} size={20} />
      <div className="run-result-body">
        <b>
          {n != null && n > 0 ? (
            <Bi en={<>Scan complete: <span className="tabular">{n}</span> {n === 1 ? "change needs" : "changes need"} your review</>} ar={<>اكتمل الفحص: {n === 1 ? "يحتاج تغيير واحد" : n === 2 ? "يحتاج تغييران" : `تحتاج ${n} ${n <= 10 ? "تغييرات" : "تغييرًا"}`} إلى مراجعتك</>} />
          ) : n === 0 ? (
            <Bi en="Scan complete: no change needs your review" ar="اكتمل الفحص: لا يوجد تغيير يحتاج إلى مراجعتك" />
          ) : (
            <Bi en="Scan complete: the changes are ready for your review" ar="اكتمل الفحص: التغييرات جاهزة لمراجعتك" />
          )}
        </b>
        <span>
          {auto != null && auto > 0 ? (
            <Bi
              en={`${auto} safe ${auto === 1 ? "action was" : "actions were"} closed automatically. The rest wait for your decision.`}
              ar={`أُغلق ${auto} ${auto === 1 ? "إجراء آمن" : "إجراءً آمنًا"} تلقائيًا، وباقي الإجراءات بانتظار قرارك.`}
            />
          ) : (
            <Bi en="Nothing is applied until you decide." ar="لن يُطبَّق أي شيء قبل أن تقرر." />
          )}
        </span>
      </div>
      <Button variant="secondary" href="/changes"><Bi en="Review changes" ar="مراجعة التغييرات" /></Button>
    </div>
  );
}
