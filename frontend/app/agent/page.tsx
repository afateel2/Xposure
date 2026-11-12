"use client";

import { useEffect, useMemo, useState } from "react";
import { AgentControlPad } from "@/components/AgentControlPad";
import { Bi } from "@/components/Bi";
import { AgentActivity } from "@/components/run/AgentActivity";
import { DemoControls } from "@/components/run/DemoControls";
import { PipelineStepper } from "@/components/run/PipelineStepper";
import { PortalCard } from "@/components/run/PortalCard";
import { RunResult } from "@/components/run/RunResult";
import { useTick } from "@/components/run/useTick";
import { Button, Card, Icon, PageHeader, RefreshCw, TriangleAlert, useToast } from "@/components/ui";
import { MessageSquareText } from "lucide-react";
import { getActivity, getAgentState, getDemoRun, getDemoStatus, resetDemo, startDemoScan } from "@/lib/api-demo";
import { getCompany } from "@/lib/api-company";
import { ApiError, errorText } from "@/lib/api-http";
import { usePoll } from "@/lib/use-poll";
import type { ActivityItem, DemoRun } from "@/lib/types-demo";

function isUnavailable(err: unknown): boolean {
  return err instanceof ApiError && err.unavailable;
}

/** When the audit feed is not available, the newest pipeline steps stand in for it (and the card says so). */
function activityFromStages(run: DemoRun | null): ActivityItem[] {
  if (!run) return [];
  return run.stages
    .filter((s) => s.status !== "pending")
    .map((s, i) => ({
      id: i + 1,
      ts: (s.status === "running" ? s.started_at : s.ended_at ?? s.started_at) ?? "",
      kind: "system",
      severity: (s.status === "failed" ? "danger" : s.status === "done" ? "success" : "info") as ActivityItem["severity"],
      icon: s.status === "failed" ? "circle-x" : s.status === "done" ? "circle-check" : "hourglass",
      text_en: s.label_en,
      text_ar: s.label_ar,
      detail_en: s.detail_en,
      detail_ar: s.detail_ar,
      actor: "agent:demo_runner",
      event: "stage",
      count: 1,
    }))
    .reverse();
}

export default function AgentPage() {
  const toast = useToast();
  const [startedRun, setStartedRun] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [resetting, setResetting] = useState(false);

  const runPoll = usePoll(getDemoRun, (d) => (d?.status === "running" ? 1000 : 4000));
  const statusPoll = usePoll(getDemoStatus, (d) => (d?.phase === "scanning" ? 2000 : 6000));
  const run = runPoll.data;
  const status = statusPoll.data;
  const running = run?.status === "running";

  const activityPoll = usePoll((s) => getActivity(8, s), () => (running ? 2500 : 10000), [run?.status]);
  const agentState = usePoll(getAgentState, 15000, [run?.status]);
  const company = usePoll(getCompany, 30000);

  const now = useTick(running);

  // The button stays in its loading state from the click until the new run shows up.
  useEffect(() => {
    if (!starting) return;
    if (run && startedRun && run.run_id === startedRun) setStarting(false);
    const id = window.setTimeout(() => setStarting(false), 15000);
    return () => window.clearTimeout(id);
  }, [starting, run, startedRun]);

  const unavailable = isUnavailable(runPoll.error) && !run;
  const scanning = running || starting;

  async function scan() {
    setStarting(true);
    try {
      const r = await startDemoScan();
      setStartedRun(r.run_id);
      if (r.already_running === true) {
        toast.info(<Bi en="A scan is already running. Showing its progress." ar="هناك فحص جارٍ بالفعل. نعرض تقدمه." />);
      }
      runPoll.reload();
      statusPoll.reload();
      activityPoll.reload();
    } catch (err) {
      setStarting(false);
      toast.error(
        <Bi
          en={<>Could not start the scan: {errorText(err)}</>}
          ar={<>تعذّر بدء الفحص: <bdi dir="auto">{errorText(err)}</bdi></>}
        />,
      );
    }
  }

  async function reset(): Promise<boolean> {
    setResetting(true);
    try {
      await resetDemo();
      toast.success(<Bi en="Demo reset to the ECC-1:2018 baseline." ar="أُعيد ضبط العرض إلى الوضع المرجعي ECC-1:2018." />);
      runPoll.reload();
      statusPoll.reload();
      activityPoll.reload();
      agentState.reload();
      company.reload();
      return true;
    } catch (err) {
      toast.error(
        <Bi
          en={<>Could not reset the demo: {errorText(err)}</>}
          ar={<>تعذّرت إعادة ضبط العرض: <bdi dir="auto">{errorText(err)}</bdi></>}
        />,
      );
      return false;
    } finally {
      setResetting(false);
    }
  }

  const followed = company.data?.applied_regulation ?? null;
  const scanDisabledReason = useMemo(() => {
    if (status && status.demo_mode === false) {
      return { en: "Demo mode is off on this server, so scanning is disabled.", ar: "وضع العرض التجريبي متوقف على هذا الخادم، لذلك الفحص معطّل." };
    }
    if (unavailable) {
      return { en: "The demo service is not available on this backend.", ar: "خدمة العرض غير متاحة على هذا الخادم." };
    }
    return null;
  }, [status, unavailable]);

  const activityUnavailable = isUnavailable(activityPoll.error);
  const stageItems = activityUnavailable ? activityFromStages(run) : null;
  const activityItems = stageItems ?? activityPoll.data?.items ?? null;

  const connectionTrouble = runPoll.error != null && !unavailable && !!run;

  return (
    <main>
      <PageHeader
        title={<Bi en="Run agent" ar="تشغيل الوكيل" />}
        subtitle={<Bi en="Scan the regulator portal, watch the pipeline work step by step, then review what it found." ar="افحص بوابة الجهة التنظيمية وتابع خطوات المعالجة مباشرة، ثم راجع ما رصده الوكيل." />}
      />

      {unavailable && (
        <div className="xp-card xp-error-card run-unavailable" role="alert">
          <Icon icon={TriangleAlert} size={20} />
          <div className="run-unavailable-text">
            <b><Bi en="The demo service is not available" ar="خدمة العرض غير متاحة" /></b>
            <span>
              <Bi
                en="This backend does not answer the demo routes. Restart it with the latest code, then retry. No progress is shown until it does."
                ar="لا يستجيب هذا الخادم لمسارات العرض. أعد تشغيله بأحدث إصدار ثم أعد المحاولة. لن يُعرض أي تقدم إلى أن يستجيب."
              />
            </span>
          </div>
          <Button variant="secondary" size="sm" icon={<Icon icon={RefreshCw} size={14} />} onClick={() => { runPoll.reload(); statusPoll.reload(); }}>
            <Bi en="Retry" ar="إعادة المحاولة" />
          </Button>
        </div>
      )}
      {connectionTrouble && (
        <p className="run-conn" role="status">
          <Icon icon={TriangleAlert} size={14} />
          <Bi en="Connection problem. Showing the last known state, retrying." ar="مشكلة في الاتصال. نعرض آخر حالة معروفة ونعيد المحاولة." />
        </p>
      )}

      <div className="run-layout">
        <div className="run-col">
          <PortalCard
            status={status}
            followed={followed}
            scanning={scanning}
            unavailable={unavailable}
            scanDisabledReason={scanDisabledReason}
            onScan={scan}
          />
          {run && <RunResult run={run} changes={agentState.data?.awaiting_changes ?? null} />}
          <AgentActivity
            items={activityItems}
            loading={activityPoll.loading}
            unavailable={activityUnavailable && !stageItems?.length}
            source={activityUnavailable ? "stages" : "audit"}
          />
        </div>
        <div className="run-col">
          <PipelineStepper run={run} now={now} onRetry={scan} retrying={starting} unavailable={unavailable} />
          <DemoControls status={status} running={running} onReset={reset} resetting={resetting} />
        </div>
      </div>

      <section className="run-command" aria-labelledby="run-command-title">
        <Card
          title={<span id="run-command-title"><Bi en="Command the agent" ar="وجّه الوكيل" /></span>}
          icon={<Icon icon={MessageSquareText} size={18} />}
        >
          <p className="run-command-intro">
            <Bi
              en="Click a suggestion or type what you want. Nothing changes until you confirm."
              ar="اختر اقتراحًا أو اكتب ما تريده، ولن يتغيّر شيء حتى تؤكد ذلك."
            />
          </p>
          <AgentControlPad />
          <p className="run-command-foot">
            <Bi
              en="Matching is deterministic keyword and entity matching, not an LLM call. This is what keeps a wrong guess from ever being applied with false confidence. Free text only ever produces a preview; approving or dismissing anything still goes through the same audited path as the buttons on the Changes screen."
              ar="المطابقة هنا حتمية بالكلمات المفتاحية والعناصر المذكورة، وليست عبر نموذج لغوي، وهذا ما يمنع تخمينًا خاطئًا من التنفيذ بثقة زائفة. النص الحر لا ينتج سوى معاينة، أما الاعتماد أو التجاهل فيمر عبر المسار المُدقَّق نفسه المستخدم في أزرار شاشة التغييرات."
            />
          </p>
        </Card>
      </section>
    </main>
  );
}
