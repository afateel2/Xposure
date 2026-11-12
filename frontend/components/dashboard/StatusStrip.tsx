"use client";

import Link from "next/link";
import { CalendarClock, Clock, GitCompare, Globe, Info, LoaderCircle, Moon, TriangleAlert, WifiOff } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Bi } from "@/components/Bi";
import { RelTime } from "@/components/RelTime";
import { Icon } from "@/components/ui";
import { useLang } from "@/lib/lang";
import { absoluteTime, ageHours, useNow } from "@/lib/time";
import type { AgentState, AgentStateName, Overview } from "@/lib/types-visibility";

interface StateView {
  tone: "muted" | "info" | "warning" | "danger";
  icon: LucideIcon;
  spin?: boolean;
  en: string;
  ar: string;
}

const STATE_VIEW: Record<AgentStateName, StateView> = {
  idle: { tone: "muted", icon: Moon, en: "Idle", ar: "في وضع الانتظار" },
  scanning: { tone: "info", icon: LoaderCircle, spin: true, en: "Scanning", ar: "جارٍ الفحص" },
  awaiting_review: { tone: "warning", icon: Clock, en: "Awaiting your review", ar: "بانتظار مراجعتك" },
  failed: { tone: "danger", icon: TriangleAlert, en: "Last run failed", ar: "تعذّر إكمال آخر تشغيل" },
};

/**
 * Agent state pill with the live stage text. `role=status` + aria-live so a
 * screen reader hears "Scanning: Diffing versions" as it changes; colour is
 * never the only signal (icon and words carry the state too).
 */
export function AgentStatePill({ state, unavailable }: { state: AgentState | null; unavailable?: boolean }) {
  const now = useNow(30_000);
  const lang = useLang();
  if (!state) {
    return (
      <div className="dash-agent" role="status" aria-live="polite">
        <span className={`dash-pill tone-${unavailable ? "danger" : "muted"}`}>
          <Icon icon={unavailable ? WifiOff : LoaderCircle} size={14} className={unavailable ? "" : "xp-spin"} />
          {unavailable ? <Bi en="Status unavailable" ar="تعذّر جلب الحالة" /> : <Bi en="Checking status" ar="جارٍ جلب الحالة" />}
        </span>
        {unavailable && (
          <span className="dash-agent-msg">
            <Bi en="The backend did not answer. Retrying automatically." ar="لم يستجب الخادم. ستُعاد المحاولة تلقائيًا." />
          </span>
        )}
      </div>
    );
  }
  const view = STATE_VIEW[state.state];
  const sinceHours = ageHours(state.since, now);
  return (
    <div className="dash-agent" role="status" aria-live="polite">
      <span className={`dash-pill tone-${view.tone}`}>
        <Icon icon={view.icon} size={14} className={view.spin ? "xp-spin" : ""} />
        <Bi en={view.en} ar={view.ar} />
      </span>
      <span className="dash-agent-msg">
        <Bi en={state.message_en} ar={state.message_ar} />
      </span>
      {state.since && sinceHours != null && (
        <span className="dash-agent-since" title={absoluteTime(state.since, lang)}>
          <Bi en="Since " ar="منذ " /><RelTime iso={state.since} />
        </span>
      )}
    </div>
  );
}

function Cell({ icon, label, children, tone }: { icon: LucideIcon; label: React.ReactNode; children: React.ReactNode; tone?: "danger" | "warning" }) {
  return (
    <div className={`dash-cell${tone ? ` tone-${tone}` : ""}`}>
      <div className="dash-cell-label"><Icon icon={icon} size={14} />{label}</div>
      <div className="dash-cell-value">{children}</div>
    </div>
  );
}

/**
 * Top status strip: what the agent is doing now, when sources were last
 * checked, when the last regulator change was detected, and how many
 * sources are really monitored (planned regulators are never counted).
 */
export function StatusStrip({
  agent, agentUnavailable, overview,
}: {
  agent: AgentState | null;
  agentUnavailable: boolean;
  overview: Overview | null;
}) {
  const m = overview?.monitoring;
  const now = useNow(60_000);
  const lang = useLang();
  const staleH = m?.stale_after_hours ?? 168;
  const lastAge = ageHours(m?.last_scan_at, now);
  const scanFailed = agent?.state === "failed";
  const checkedTone = scanFailed ? "danger" : lastAge == null || lastAge > staleH ? "warning" : undefined;

  return (
    <section className="dash-strip xp-card" aria-label="Status">
      <div className="dash-strip-agent">
        <AgentStatePill state={agent} unavailable={agentUnavailable} />
      </div>
      <div className="dash-strip-cells">
        <Cell icon={Clock} label={<Bi en="Last checked" ar="آخر فحص" />} tone={checkedTone}>
          {scanFailed ? (
            <span className="dash-strong"><Bi en="Failed, " ar="تعذّر الفحص، " /><RelTime iso={agent?.since ?? m?.last_scan_at} /></span>
          ) : (
            <span className="dash-strong"><RelTime iso={m?.last_scan_at} never={<Bi en="Never checked" ar="لم يُفحص بعد" />} /></span>
          )}
          {m?.last_scan_at && <span className="dash-abs">{absoluteTime(m.last_scan_at, lang)}</span>}
        </Cell>
        <Cell icon={GitCompare} label={<Bi en="Last change detected" ar="آخر تغيير مرصود" />}>
          <span className="dash-strong">
            <RelTime iso={m?.last_release_detected_at} never={<Bi en="No change detected" ar="لم يُرصد تغيير" />} />
          </span>
          {m?.last_release_detected_at && <span className="dash-abs">{absoluteTime(m.last_release_detected_at, lang)}</span>}
        </Cell>
        <Cell icon={Globe} label={<Bi en="Sources monitored" ar="المصادر المراقَبة" />}>
          {m ? (
            <>
              <span className="dash-strong tabular">
                <Bi en={`${m.sources_ok} of ${m.sources_total} monitored`} ar={`${m.sources_ok} من ${m.sources_total} مصدرًا مراقَبًا`} />
              </span>
              {m.sources_planned > 0 && (
                <span className="dash-abs">
                  <Icon icon={CalendarClock} size={12} />
                  <Bi en={`${m.sources_planned} more planned`} ar={`${m.sources_planned} أخرى مخطط لها`} />
                </span>
              )}
            </>
          ) : (
            <span className="dash-abs">{" "}</span>
          )}
        </Cell>
      </div>
      {m && (
        <p className="dash-scope">
          <Icon icon={Info} size={13} />
          <span><Bi en={m.scope_note_en} ar={m.scope_note_ar} />{" "}
            <Link href="/sources" className="dash-inline-link"><Bi en="Regulatory sources" ar="المصادر التنظيمية" /></Link>
          </span>
        </p>
      )}
    </section>
  );
}
