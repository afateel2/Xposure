"use client";

import { useEffect, useState } from "react";
import { Bi } from "@/components/Bi";
import { Badge, BrandMotif, Card, DataTable, Icon, PageHeader, ShieldCheck } from "@/components/ui";
import { getPolicy, getReceivedWebhooks, getSentNotifications } from "@/lib/api";
import { t, useLang } from "@/lib/lang";
import { ACTION_TYPE_LABEL, AUTOMATION_LEVEL_LABEL, CHANGE_TYPE_LABEL } from "@/lib/labels";
import type { PolicyOut, ReceivedWebhookOut, SentNotificationOut } from "@/lib/types";

export default function SettingsPage() {
  const lang = useLang();
  const [policy, setPolicy] = useState<PolicyOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [webhookEvents, setWebhookEvents] = useState<ReceivedWebhookOut[] | null>(null);
  const [sentNotifications, setSentNotifications] = useState<SentNotificationOut[] | null>(null);

  useEffect(() => {
    getPolicy()
      .then(setPolicy)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
    getReceivedWebhooks()
      .then(setWebhookEvents)
      .catch(() => setWebhookEvents([]));
    getSentNotifications()
      .then(setSentNotifications)
      .catch(() => setSentNotifications([]));
  }, []);

  const minConfidence = policy ? Math.round(policy.min_auto_execute_confidence * 100) : 0;

  return (
    <main>
      <PageHeader
        title={<Bi en="Settings: automation policy" ar="الإعدادات: سياسة الأتمتة" />}
        subtitle={
          <Bi
            en="An admin sets the requested automation levels; code decides what is actually granted"
            ar="يحدد مدير النظام مستويات الأتمتة المطلوبة، والكود هو من يقرر ما يُمنح فعليًا"
          />
        }
      />

      {error && (
        <Card className="xp-error-card" role="alert">
          <span className="text-danger">{error}</span>
        </Card>
      )}
      {!error && policy === null && (
        <Card><BrandMotif variant="spinner" title={<Bi en="Loading policy" ar="جارٍ تحميل السياسة" />} /></Card>
      )}

      {!error && policy && (
        <>
          <div className="set-top">
            <Card flush title={<Bi en="Automation level per action type" ar="مستوى الأتمتة لكل نوع إجراء" />}>
              <DataTable caption={<Bi en="Automation policy matrix" ar="مصفوفة سياسة الأتمتة" />}>
                <thead>
                  <tr>
                    <th><Bi en="Action type" ar="نوع الإجراء" /></th>
                    <th><Bi en="Requested level" ar="المستوى المطلوب" /></th>
                    <th><Bi en="Can ever auto-execute?" ar="هل يمكن تنفيذه تلقائيًا؟" /></th>
                  </tr>
                </thead>
                <tbody>
                  {policy.action_types.map((actionType) => {
                    const level = policy.action_levels[actionType] ?? policy.default_level;
                    const canAuto = policy.auto_executable_action_types.includes(actionType);
                    return (
                      <tr key={actionType}>
                        <td>
                          <Bi en={ACTION_TYPE_LABEL[actionType]?.en ?? actionType} ar={ACTION_TYPE_LABEL[actionType]?.ar ?? actionType} />
                        </td>
                        <td>
                          <Bi en={AUTOMATION_LEVEL_LABEL[level]?.en ?? level} ar={AUTOMATION_LEVEL_LABEL[level]?.ar ?? level} />
                        </td>
                        <td>
                          {canAuto ? (
                            <Badge variant="approved"><Bi en="Yes" ar="نعم" /></Badge>
                          ) : (
                            <Badge variant="neutral"><Bi en="Never" ar="أبدًا" /></Badge>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </DataTable>
            </Card>

            <div className="stack" style={{ gap: 16 }}>
              <Card
                icon={<Icon icon={ShieldCheck} size={18} />}
                title={<Bi en="Hard gates" ar="ضوابط صارمة" />}
              >
                <p className="xp-muted" style={{ fontSize: 13, marginBlockEnd: 12 }}>
                  <Bi en="Cannot be overridden by the policy file." ar="لا يمكن تجاوزها عبر ملف السياسة." />
                </p>
                <ul className="set-gates">
                  {policy.gates.map((gate) => (
                    <li key={gate.id}>
                      <Icon icon={ShieldCheck} size={15} />
                      <span dir="auto">{gate.description_en}</span>
                    </li>
                  ))}
                  <li>
                    <Icon icon={ShieldCheck} size={15} />
                    <span>
                      <Bi
                        en={`Minimum confidence to auto-execute anything: ${minConfidence}%.`}
                        ar={`الحد الأدنى للثقة اللازمة لأي تنفيذ تلقائي: ${minConfidence}٪.`}
                      />
                    </span>
                  </li>
                </ul>
              </Card>

              <Card title={<Bi en="Change types that may ever auto-close" ar="أنواع التغييرات التي يمكن إغلاقها تلقائيًا" />}>
                <div className="row" style={{ gap: 8 }}>
                  {policy.auto_executable_change_types.map((ct) => (
                    <Badge key={ct} variant="neutral">
                      <Bi en={CHANGE_TYPE_LABEL[ct]?.en ?? ct} ar={CHANGE_TYPE_LABEL[ct]?.ar ?? ct} />
                    </Badge>
                  ))}
                </div>
              </Card>
            </div>
          </div>

          <h2 className="xp-section-title"><Bi en="Delegation notifications" ar="إشعارات الإسناد" /></h2>
          <Card flush headless>
            <DataTable caption={<Bi en="Delegation notifications" ar="إشعارات الإسناد" />}>
              <thead>
                <tr>
                  <th><Bi en="Sent" ar="وقت الإرسال" /></th>
                  <th><Bi en="Action" ar="الإجراء" /></th>
                  <th><Bi en="Assigned to" ar="أُسنِد إلى" /></th>
                  <th><Bi en="Delivery" ar="التسليم" /></th>
                </tr>
              </thead>
              <tbody>
                {sentNotifications === null && (
                  <tr>
                    <td colSpan={4}><BrandMotif variant="spinner" compact title={<Bi en="Loading" ar="جارٍ التحميل" />} /></td>
                  </tr>
                )}
                {sentNotifications && sentNotifications.length === 0 && (
                  <tr>
                    <td colSpan={4}>
                      <BrandMotif
                        variant="empty"
                        compact
                        title={<Bi en="No actions delegated yet" ar="لم يُسنَد أي إجراء بعد" />}
                        hint={<Bi en="Assign an action to someone from a change's full page to see it here." ar="أسنِد إجراءً إلى شخص من الصفحة الكاملة لأحد التغييرات لرؤيته هنا." />}
                      />
                    </td>
                  </tr>
                )}
                {sentNotifications?.map((n) => (
                  <tr key={n.id}>
                    <td className="mono"><bdi>{new Date(n.ts).toLocaleString()}</bdi></td>
                    <td className="mono">#{n.action_id}</td>
                    <td><bdi>{n.assignee_name ?? "-"}</bdi></td>
                    <td>
                      {n.notification?.sent ? (
                        <Badge variant="approved"><Bi en={`Sent via ${n.notification.channel}`} ar={<>أُرسل عبر <bdi>{n.notification.channel}</bdi></>} /></Badge>
                      ) : (
                        <span title={n.notification?.reason ?? undefined}>
                          <Badge variant="pending"><Bi en="Not sent" ar="لم يُرسَل" /></Badge>
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          </Card>

          <h2 className="xp-section-title"><Bi en="Outbound webhook activity (demo receiver)" ar="نشاط الويب هوك الصادر (مستقبل تجريبي)" /></h2>
          <Card flush headless>
            <DataTable caption={<Bi en="Outbound webhook activity" ar="نشاط الويب هوك الصادر" />}>
              <thead>
                <tr>
                  <th><Bi en="Received" ar="وقت الاستلام" /></th>
                  <th><Bi en="Event" ar="الحدث" /></th>
                  <th><Bi en="Trust" ar="الموثوقية" /></th>
                  <th><Bi en="Payload" ar="المحتوى" /></th>
                </tr>
              </thead>
              <tbody>
                {webhookEvents === null && (
                  <tr>
                    <td colSpan={4}><BrandMotif variant="spinner" compact title={<Bi en="Loading" ar="جارٍ التحميل" />} /></td>
                  </tr>
                )}
                {webhookEvents && webhookEvents.length === 0 && (
                  <tr>
                    <td colSpan={4}>
                      <BrandMotif
                        variant="empty"
                        compact
                        title={<Bi en="No webhooks received yet" ar="لم يصل أي حدث بعد" />}
                        hint={
                          <Bi
                            en="Set WEBHOOK_URL to this app's own /webhooks/receiver in .env to see change.detected, impact.computed and action.approved events arrive here."
                            ar={<>لعرض أحداث <bdi>change.detected</bdi> و<bdi>impact.computed</bdi> و<bdi>action.approved</bdi> هنا، اضبط <bdi>WEBHOOK_URL</bdi> في <bdi>.env</bdi> على عنوان <bdi>/webhooks/receiver</bdi> الخاص بالتطبيق نفسه.</>}
                          />
                        }
                      />
                    </td>
                  </tr>
                )}
                {webhookEvents?.map((e) => {
                  const verified = e.payload._verified === true;
                  return (
                    <tr key={e.id}>
                      <td className="mono"><bdi>{new Date(e.ts).toLocaleString()}</bdi></td>
                      <td className="mono">{e.event}</td>
                      <td>
                        {verified ? (
                          <Badge variant="approved"><Bi en="Signature verified" ar="تم التحقق من التوقيع" /></Badge>
                        ) : (
                          <span title={t(lang, "No WEBHOOK_SECRET was configured when this arrived: accepted on faith, not cryptographically verified.", "لم يكن WEBHOOK_SECRET مضبوطًا عند الاستلام: قُبل الحدث دون تحقق تشفيري.")}>
                            <Badge variant="pending"><Bi en="Unverified" ar="غير موثّق" /></Badge>
                          </span>
                        )}
                      </td>
                      <td className="mono set-payload" dir="ltr">{JSON.stringify(e.payload)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </DataTable>
          </Card>
        </>
      )}
    </main>
  );
}
