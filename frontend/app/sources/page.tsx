"use client";

import { useEffect, useState } from "react";
import { Bi } from "@/components/Bi";
import { Badge, Button, BrandMotif, Card, DataTable, Icon, Info, PageHeader, StatCard, useToast } from "@/components/ui";
import { Radar as RadarIcon } from "lucide-react";
import { checkLivePortal, type LiveCheckResult } from "@/lib/api-watcher";
import { getSources } from "@/lib/api";
import type { SourceVersionOut } from "@/lib/types";

const STATUS_LABEL: Record<LiveCheckResult["status"], { en: string; ar: string; tone: string }> = {
  new_version_available: { en: "New version live", ar: "نسخة جديدة متاحة", tone: "warning" },
  matches_known: { en: "Matches what is ingested", ar: "مطابقة لما تم إدخاله", tone: "success" },
  content_conflict: { en: "Content differs from ingested copy", ar: "المحتوى مختلف عن النسخة المُدخلة", tone: "danger" },
};

export default function SourcesPage() {
  const toast = useToast();
  const [sources, setSources] = useState<SourceVersionOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [liveChecks, setLiveChecks] = useState<Record<string, LiveCheckResult>>({});
  const [checking, setChecking] = useState<string | null>(null);

  useEffect(() => {
    getSources()
      .then(setSources)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  async function runLiveCheck(regulator: string, regulation: string) {
    const key = `${regulator}:${regulation}`;
    setChecking(key);
    try {
      const result = await checkLivePortal(regulator, regulation);
      setLiveChecks((prev) => ({ ...prev, [key]: result }));
      const label = STATUS_LABEL[result.status];
      const toastFn = result.status === "content_conflict" ? toast.warning : result.status === "new_version_available" ? toast.info : toast.success;
      toastFn(<Bi en={`${regulator.toUpperCase()}: ${label.en}`} ar={`${regulator.toUpperCase()}: ${label.ar}`} />);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(<Bi en={message.split(" | ")[0]} ar={message.split(" | ")[1] ?? message} />);
    } finally {
      setChecking(null);
    }
  }

  const regulatorCount = sources ? new Set(sources.map((s) => s.regulator.code)).size : 0;
  const regulationCount = sources ? new Set(sources.map((s) => s.regulation.code)).size : 0;
  const clauseCount = sources ? sources.reduce((sum, s) => sum + s.clause_count, 0) : 0;

  return (
    <main>
      <PageHeader
        title={<Bi en="Regulatory sources" ar="المصادر التنظيمية" />}
        subtitle={<Bi en="Every ingested regulation version, immutable once written" ar="كل نسخة نظام تمّ إدخالها، وهي غير قابلة للتعديل بعد التسجيل" />}
      />

      {error && (
        <Card className="xp-error-card" role="alert">
          <span className="text-danger">{error}</span>
        </Card>
      )}
      {!error && sources === null && (
        <Card><BrandMotif variant="spinner" title={<Bi en="Loading sources" ar="جارٍ تحميل المصادر" />} /></Card>
      )}
      {!error && sources !== null && sources.length === 0 && (
        <Card>
          <BrandMotif
            variant="empty"
            title={<Bi en="No regulations ingested yet" ar="لم يتم إدخال أي نظام بعد" />}
            hint={<Bi en="Run a scan from the Run agent page to fetch the first regulation version." ar="شغّل فحصاً من صفحة تشغيل الوكيل لجلب أول إصدار من الأنظمة." />}
          />
        </Card>
      )}

      {!error && sources !== null && sources.length > 0 && (
        <>
          <div className="xp-grid cols-3" style={{ marginBlockEnd: 20 }}>
            <StatCard label={<Bi en="Regulators" ar="الجهات التنظيمية" />} value={regulatorCount} />
            <StatCard label={<Bi en="Regulations tracked" ar="الأنظمة المتابعة" />} value={regulationCount} trend={<Bi en={`${sources.length} ingested versions`} ar={`${sources.length} إصدارات مُدخلة`} />} />
            <StatCard label={<Bi en="Clauses ingested" ar="البنود المُدخلة" />} value={clauseCount} />
          </div>

          <DataTable caption={<Bi en="Ingested regulation versions" ar="إصدارات الأنظمة المُدخلة" />}>
            <thead>
              <tr>
                <th><Bi en="Regulator" ar="الجهة التنظيمية" /></th>
                <th><Bi en="Regulation" ar="النظام" /></th>
                <th><Bi en="Version" ar="الإصدار" /></th>
                <th className="num"><Bi en="Clauses" ar="البنود" /></th>
                <th><Bi en="Ingested" ar="تاريخ الإدخال" /></th>
                <th><Bi en="Source SHA-256" ar="بصمة المصدر" /></th>
                <th><Bi en="Live portal" ar="البوابة المباشرة" /></th>
              </tr>
            </thead>
            <tbody>
              {sources.map((source) => {
                const key = `${source.regulator.code}:${source.regulation.code}`;
                const liveResult = liveChecks[key];
                const liveLabel = liveResult ? STATUS_LABEL[liveResult.status] : null;
                return (
                  <tr key={`${source.regulation.code}-${source.version_label}`}>
                    <td>
                      <Badge variant="neutral">{source.regulator.code.toUpperCase()}</Badge>
                      <div className="xp-muted" style={{ fontSize: 12, marginBlockStart: 4 }}>
                        <Bi en={source.regulator.name_en} ar={source.regulator.name_ar || source.regulator.name_en} />
                      </div>
                    </td>
                    <td>
                      <Bi en={source.regulation.title_en} ar={source.regulation.title_ar || source.regulation.title_en} />
                    </td>
                    <td className="mono">{source.version_label}</td>
                    <td className="num">{source.clause_count}</td>
                    <td className="mono">{new Date(source.ingested_at).toISOString().slice(0, 10)}</td>
                    <td className="mono" title={source.file_sha256}><bdi>
                      {source.file_sha256.slice(0, 10)}...{source.file_sha256.slice(-8)}</bdi>
                    </td>
                    <td>
                      {source.has_live_check ? (
                        <div className="stack" style={{ gap: 4 }}>
                          <Button
                            variant="secondary"
                            size="sm"
                            icon={<Icon icon={RadarIcon} size={14} />}
                            loading={checking === key}
                            onClick={() => runLiveCheck(source.regulator.code, source.regulation.code)}
                          >
                            <Bi en="Check now" ar="تحقق الآن" />
                          </Button>
                          {liveResult && liveLabel && (
                            <div style={{ fontSize: 11.5 }}>
                              <Badge variant={liveLabel.tone as "warning" | "success" | "danger"}>
                                <Bi en={liveLabel.en} ar={liveLabel.ar} />
                              </Badge>
                              {" "}<bdi className="mono xp-muted">({liveResult.live_version_label})</bdi>
                            </div>
                          )}
                        </div>
                      ) : (
                        <span className="xp-muted" style={{ fontSize: 12 }}>
                          <Bi en="Not available yet" ar="غير متاح بعد" />
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </DataTable>
        </>
      )}

      <footer className="note">
        <Icon icon={Info} size={16} />
        <Bi
          en="Every alert in the Changes screen links back to one of these rows by SHA-256 and page number: the guardrail that no alert can point at an unverifiable source."
          ar="يرتبط كل تنبيه في شاشة التغييرات بأحد هذه الصفوف عبر بصمة SHA-256 ورقم الصفحة، وهي الضمانة بأن لا تنبيه بلا مصدر يمكن التحقق منه."
        />
      </footer>
    </main>
  );
}
