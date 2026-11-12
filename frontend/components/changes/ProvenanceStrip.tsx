"use client";

import { useEffect, useState } from "react";
import { Cpu, ShieldCheck, Sparkles } from "lucide-react";
import { Bi } from "@/components/Bi";
import { Badge, Card, ConfidenceBar, Icon } from "@/components/ui";
import { getPolicy } from "@/lib/api";
import { CHANGE_TYPE_LABEL, MATCH_KIND_LABEL } from "@/lib/labels";
import type { ChangeDetailOut } from "@/lib/types";

/**
 * Provenance: which parts of this change were decided by code (matching of
 * clauses, priority arithmetic) and which were only labelled by the model
 * (change type and confidence). The confidence bar carries the auto-execute
 * threshold from the automation policy, read live; if it cannot be read the
 * marker is hidden instead of guessed.
 */
export function ProvenanceStrip({ detail }: { detail: ChangeDetailOut }) {
  const [threshold, setThreshold] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    getPolicy()
      .then((p) => {
        if (!cancelled) setThreshold(p.min_auto_execute_confidence);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const match = MATCH_KIND_LABEL[detail.match_kind] ?? { en: detail.match_kind, ar: detail.match_kind };
  const typeLabel = detail.change_type ? CHANGE_TYPE_LABEL[detail.change_type] : null;
  const below = threshold != null && detail.confidence != null && detail.confidence < threshold;

  return (
    <div className="chg-prov" role="group" aria-label="Provenance">
      <Card headless pad={false} className="chg-prov-card">
        <div className="chg-prov-inner">
          <span className="chg-prov-chip is-code">
            <Icon icon={ShieldCheck} size={15} />
            <Bi en="Detected by code" ar="رصدها الكود" />
          </span>
          <p className="chg-prov-main">
            <b><Bi en={match.en.charAt(0).toUpperCase() + match.en.slice(1)} ar={match.ar} /></b>
            {detail.match_kind === "renumbered_candidate" && detail.match_score != null && (
              <span className="xp-muted tabular"> · <Bi en="similarity" ar="التشابه" /> {Math.round(detail.match_score * 100)}%</span>
            )}
          </p>
          <p className="chg-prov-note">
            <Bi
              en="Clause IDs, text, page numbers and the diff are compared by code. No model is involved in what changed."
              ar="تُقارن معرّفات البنود والنصوص وأرقام الصفحات والفروقات بالكود، ولا يتدخل أي نموذج في تحديد ما تغيّر."
            />
          </p>
        </div>
      </Card>

      <Card headless pad={false} className="chg-prov-card">
        <div className="chg-prov-inner">
          <span className="chg-prov-chip is-model">
            <Icon icon={Sparkles} size={15} />
            <Bi en="Classified by model" ar="صنّفها النموذج" />
          </span>
          <p className="chg-prov-main">
            {typeLabel ? (
              <Badge variant="neutral"><Bi en={typeLabel.en} ar={typeLabel.ar} /></Badge>
            ) : (
              <span className="xp-muted"><Bi en="Not classified yet" ar="لم يُصنَّف بعد" /></span>
            )}
          </p>
          {detail.confidence != null && (
            <div className={threshold == null ? "chg-conf-nomark" : undefined}>
              <ConfidenceBar
                value={detail.confidence}
                threshold={threshold ?? 0.7}
                label={<Bi en="Model confidence" ar="ثقة النموذج" />}
                note={
                  threshold == null ? undefined : below ? (
                    <Bi
                      en={`Below the ${Math.round(threshold * 100)}% threshold: a person decides, nothing runs automatically.`}
                      ar={`أقل من الحد ${Math.round(threshold * 100)}%: يقرر شخص، ولا يُنفَّذ شيء تلقائيًا.`}
                    />
                  ) : (
                    <Bi
                      en={`Marker: ${Math.round(threshold * 100)}% auto-execute threshold from the policy.`}
                      ar={`العلامة: حد التنفيذ التلقائي ${Math.round(threshold * 100)}% من سياسة الأتمتة.`}
                    />
                  )
                }
              />
            </div>
          )}
          <p className="chg-prov-note">
            <Icon icon={Cpu} size={13} />{" "}
            <Bi
              en="The model only labels. Deadlines, impact and priority are computed by code."
              ar="يقتصر دور النموذج على التصنيف، أما المواعيد والأثر والأولوية فيحسبها الكود."
            />
          </p>
        </div>
      </Card>
    </div>
  );
}
