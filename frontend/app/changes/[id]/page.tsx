"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Bi } from "@/components/Bi";
import { ChangeDetailPanel } from "@/components/ChangeDetailPanel";
import { DueLabel } from "@/components/changes/DueLabel";
import { RelTime } from "@/components/changes/RelTime";
import { Badge, BrandMotif, Card, PageHeader, PriorityPill } from "@/components/ui";
import { getChange } from "@/lib/api";
import { CHANGE_TYPE_LABEL } from "@/lib/labels";
import { useReviewQueue } from "@/lib/review-queue";
import type { ChangeDetailOut } from "@/lib/types";

export default function ChangeDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  // Loaded once and kept while moving between changes (this page component persists across them).
  const queue = useReviewQueue(id);
  const [detail, setDetail] = useState<ChangeDetailOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDetail(null);
    setError(null);
    getChange(id)
      .then(setDetail)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [id]);

  // This page holds far more (impact, timeline, receipts, ERP cards) than the
  // inline row expand: widen the content column just for it. Same direct-DOM
  // attribute pattern lib/lang.ts uses for the language toggle.
  useEffect(() => {
    document.body.dataset.wide = "true";
    return () => {
      delete document.body.dataset.wide;
    };
  }, []);

  const back = { href: "/changes", label: <Bi en="Back to changes" ar="العودة إلى التغييرات" /> };

  if (error) {
    return (
      <main>
        <PageHeader title={<Bi en="Change not available" ar="التغيير غير متاح" />} back={back} />
        <Card className="xp-error-card" headless>
          <p role="alert">
            {/: 404$/.test(error) ? (
              <Bi
                en="This change does not exist (the data may have been reset or rescanned). Go back to the list to pick a current one."
                ar="هذا التغيير غير موجود (ربما أُعيد ضبط البيانات أو أُجري فحص جديد). ارجع إلى القائمة لاختيار تغيير حالي."
              />
            ) : (
              <Bi en={`Could not load this change. ${error}`} ar={`تعذّر تحميل هذا التغيير. ${error}`} />
            )}
          </p>
        </Card>
      </main>
    );
  }

  if (!detail) {
    return (
      <main>
        <PageHeader title={<Bi en="Change details" ar="تفاصيل التغيير" />} back={back} />
        <BrandMotif variant="spinner" title={<Bi en="Loading..." ar="جارٍ التحميل..." />} />
      </main>
    );
  }

  const typeLabel = detail.change_type ? CHANGE_TYPE_LABEL[detail.change_type] : null;
  const regCode = `${detail.regulator.code.toUpperCase()} ${detail.regulation.code.toUpperCase()}`;

  return (
    <main className="chg-page">
      <PageHeader
        back={back}
        title={
          <>
            {detail.clause_ref ? <bdi className="chg-title-ref mono">{detail.clause_ref}</bdi> : <Bi en="Clause" ar="بند" />}
            {typeLabel && (
              <>
                <span className="chg-title-sep" aria-hidden="true">·</span>
                <Bi en={typeLabel.en} ar={typeLabel.ar} />
              </>
            )}
          </>
        }
        subtitle={
          <>
            <bdi>{regCode}</bdi>
            {" · "}
            <Bi en={detail.regulation.title_en} ar={detail.regulation.title_ar} />
          </>
        }
      />

      <div className="chg-meta" aria-label="Change facts">
        <PriorityPill band={detail.priority_band} />
        <Badge variant="neutral"><Bi en={`Score ${detail.priority_score}`} ar={`الدرجة ${detail.priority_score}`} /></Badge>
        <DueLabel dueDate={detail.due_date} overdue={detail.is_overdue} />
        <span className="chg-meta-item">
          <RelTime value={detail.created_at} prefixEn="Detected" prefixAr="رُصد" withAbsolute />
        </span>
        <span className="chg-meta-item">
          <Bi en={`${detail.impacted_node_count} impacted`} ar={`${detail.impacted_node_count} عنصر متأثر`} />
        </span>
      </div>

      <ChangeDetailPanel key={detail.id} detail={detail} mode="full" queue={queue} />
    </main>
  );
}
