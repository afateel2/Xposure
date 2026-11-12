"use client";

import { Bi } from "@/components/Bi";
import { RelTime } from "@/components/RelTime";
import { Badge, Button, Card, Icon, Globe } from "@/components/ui";
import { Landmark, Radar as RadarIcon } from "lucide-react";
import type { DemoPhase, DemoStatus } from "@/lib/types-demo";
import { versionName } from "./format";

const PHASE_BADGE: Record<DemoPhase, { variant: "neutral" | "new" | "pending"; en: string; ar: string }> = {
  baseline: { variant: "neutral", en: "Baseline", ar: "الوضع المرجعي" },
  scanning: { variant: "new", en: "Scanning", ar: "قيد الفحص" },
  review_ready: { variant: "pending", en: "Review ready", ar: "جاهز للمراجعة" },
};

function PhaseText({ phase, followed }: { phase: DemoPhase; followed: string | null }) {
  const v = followed ? <bdi>{followed}</bdi> : null;
  if (phase === "baseline") {
    return (
      <Bi
        en={<>Your company follows {v ?? "the baseline version"}. No new version has been fetched.</>}
        ar={<>تلتزم شركتك حاليًا بالإصدار {v ?? "المرجعي"}. لم يُجلب أي إصدار جديد بعد.</>}
      />
    );
  }
  if (phase === "scanning") {
    return (
      <Bi
        en={<>The agent is checking the regulator portal and analysing the new version. Your company still follows {v ?? "the baseline version"}.</>}
        ar={<>يفحص الوكيل بوابة الجهة التنظيمية ويحلّل الإصدار الجديد. ما زالت شركتك ملتزمة بالإصدار {v ?? "المرجعي"}.</>}
      />
    );
  }
  return (
    <Bi
      en={<>The new version has been fetched and analysed. The changes are waiting for your decision. Your company still follows {v ?? "the baseline version"} until they are applied.</>}
      ar={<>جُلب الإصدار الجديد وحُلّل، والتغييرات بانتظار قرارك. ما زالت شركتك ملتزمة بالإصدار {v ?? "المرجعي"} إلى حين تطبيقها.</>}
    />
  );
}

/**
 * "Regulator portal": what is being monitored, the current phase, the
 * versions the agent holds, and the one primary button of the page (Scan
 * now). The honest note about the simulated portal sits right under it.
 */
export function PortalCard({
  status, followed, scanning, unavailable, scanDisabledReason, onScan,
}: {
  status: DemoStatus | null;
  followed: string | null;
  scanning: boolean;
  unavailable: boolean;
  scanDisabledReason: { en: string; ar: string } | null;
  onScan: () => void;
}) {
  const phase = status?.phase ?? null;
  const badge = phase ? PHASE_BADGE[phase] : null;
  const versions = status?.regulation_versions ?? [];
  const docs = status?.portal?.documents ?? [];
  const disabled = scanning || unavailable || scanDisabledReason !== null || !status;

  return (
    <Card title={<Bi en="Regulator portal" ar="بوابة الجهة التنظيمية" />} icon={<Icon icon={Globe} size={18} />} actions={badge ? <Badge variant={badge.variant}><Bi en={badge.en} ar={badge.ar} /></Badge> : null} className="run-portal">
      <div className="run-source">
        <span className="run-source-icon" aria-hidden="true"><Icon icon={Landmark} size={22} /></span>
        <div>
          <div className="run-source-name">
            <Bi en="National Cybersecurity Authority" ar="الهيئة الوطنية للأمن السيبراني" /> <bdi>(NCA)</bdi>
          </div>
          <div className="run-source-sub">
            <Bi en="Essential Cybersecurity Controls" ar="الضوابط الأساسية للأمن السيبراني" /> <bdi>(ECC)</bdi>
          </div>
        </div>
      </div>

      <p className="run-phase-text">
        {phase ? <PhaseText phase={phase} followed={followed} /> : unavailable
          ? <Bi en="The demo service does not answer, so the current phase is unknown." ar="خدمة العرض لا تستجيب، لذا تعذّر تحديد المرحلة الحالية." />
          : <Bi en="Loading the current phase" ar="جارٍ تحميل المرحلة الحالية" />}
      </p>

      {(versions.length > 0 || docs.length > 0) && (
        <div className="run-versions">
          <div className="run-versions-title"><Bi en="On the portal mirror" ar="في النسخة المحلية للبوابة" /></div>
          <ul>
            {docs.length > 0
              ? docs.map((d) => {
                const known = versions.find((v) => v.version_label === d.version_label);
                const label = versionName(known?.regulation ?? "ecc", d.version_label);
                return (
                  <li key={d.path ?? d.filename}>
                    <bdi className="mono">{label}</bdi>
                    {known ? <span className="run-versions-meta"><bdi className="tabular">{known.clause_count}</bdi> <Bi en="clauses held" ar="بندًا محفوظًا" /></span> : null}
                    {d.status === "new"
                      ? <Badge variant="new"><Bi en="New" ar="جديد" /></Badge>
                      : d.status === "known"
                        ? <Badge variant="neutral"><Bi en="Fetched" ar="مجلوب" /></Badge>
                        : <Badge variant="pending"><Bi en="Needs attention" ar="يحتاج مراجعة" /></Badge>}
                  </li>
                );
              })
              : versions.map((v) => (
                <li key={`${v.regulation}-${v.version_label}`}>
                  <bdi className="mono">{versionName(v.regulation, v.version_label)}</bdi>
                  <span className="run-versions-meta"><bdi className="tabular">{v.clause_count}</bdi> <Bi en="clauses held" ar="بندًا محفوظًا" /></span>
                  <Badge variant="neutral"><Bi en="Fetched" ar="مجلوب" /></Badge>
                </li>
              ))}
          </ul>
        </div>
      )}

      <div className="run-cta">
        <Button variant="primary" size="lg" block icon={<Icon icon={RadarIcon} size={18} />} loading={scanning} disabled={disabled} onClick={onScan}>
          {scanning ? <Bi en="Scanning..." ar="جارٍ الفحص..." /> : <Bi en="Scan now" ar="افحص الآن" />}
        </Button>
        {scanDisabledReason && !scanning && (
          <p className="run-cta-reason" role="note"><Bi en={scanDisabledReason.en} ar={scanDisabledReason.ar} /></p>
        )}
        <p className="run-note">
          <Bi
            en="The guided demo replays the regulator portal from a local mirror so a scan is fast and repeatable. A live check against the regulator's own page is on the Sources screen."
            ar="يعيد العرض الموجّه تشغيل بوابة الجهة التنظيمية من نسخة محلية مطابقة ليكون الفحص سريعًا وقابلًا للتكرار. ويتوفر فحص مباشر لصفحة الجهة التنظيمية نفسها في شاشة المصادر."
          />
        </p>
      </div>
      {status?.last_reset_at && (
        <p className="run-portal-foot"><Bi en="Demo last reset" ar="آخر إعادة ضبط للعرض" /> <RelTime iso={status.last_reset_at} /></p>
      )}
    </Card>
  );
}
