"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { ExternalLink, FileText, Plug, RefreshCw } from "lucide-react";
import { Bi } from "@/components/Bi";
import { Badge, Button, Card, Icon, PageHeader, buttonClass, useToast, type BadgeVariant } from "@/components/ui";
import { erpIsConnected, getErpStatus, type ErpStatusFull } from "@/lib/api-erp";
import { usePoll } from "@/lib/use-poll";

/**
 * Every connection between Xposure and the outside, with what it reads, what
 * it writes and what exists today. The Odoo card is live (it asks the backend);
 * the rest state plainly whether they are built, optional, a stub, blocked or
 * only planned, because a page like this is only useful if it does not oversell.
 */

type Permission = "readonly" | "approval" | "download" | "events";

const PERMISSION_LABEL: Record<Permission, { en: string; ar: string }> = {
  readonly: { en: "Read only", ar: "قراءة فقط" },
  approval: { en: "Writes after a person approves", ar: "يكتب بعد اعتماد شخص" },
  download: { en: "Writes a file you download", ar: "يكتب ملفًا تنزّله أنت" },
  events: { en: "Sends events", ar: "يرسل أحداثًا" },
};

interface Card_ {
  key: string;
  title: ReactNode;
  status: { variant: BadgeVariant; label: ReactNode };
  permission: Permission | null;
  reads: ReactNode;
  writes: ReactNode;
  extra?: ReactNode;
}

function Row({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="int-row">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function IntegrationCard({ c }: { c: Card_ }) {
  return (
    <Card as="article" className="int-card" title={c.title} icon={<Icon icon={Plug} size={18} />} actions={<Badge variant={c.status.variant}>{c.status.label}</Badge>}>
      <dl className="int-rows">
        {c.permission && (
          <Row label={<Bi en="Permission" ar="الصلاحية" />}>
            <Bi en={PERMISSION_LABEL[c.permission].en} ar={PERMISSION_LABEL[c.permission].ar} />
          </Row>
        )}
        <Row label={<Bi en="What it reads" ar="ما الذي يقرؤه" />}>{c.reads}</Row>
        <Row label={<Bi en="What it writes" ar="ما الذي يكتبه" />}>{c.writes}</Row>
      </dl>
      {c.extra && <div className="int-extra">{c.extra}</div>}
    </Card>
  );
}

function odooStatus(status: ErpStatusFull | null, loading: boolean, failed: boolean): { variant: BadgeVariant; label: ReactNode } {
  if (loading) return { variant: "neutral", label: <Bi en="Checking..." ar="جارٍ الفحص..." /> };
  if (failed || !status) return { variant: "neutral", label: <Bi en="Status unavailable" ar="الحالة غير متاحة" /> };
  if (!status.configured) return { variant: "neutral", label: <Bi en="Not configured" ar="غير مهيأ" /> };
  if (erpIsConnected(status)) return { variant: "success", label: <Bi en="Connected" ar="متصل" /> };
  return { variant: "danger", label: <Bi en="Not working" ar="لا يعمل" /> };
}

export default function IntegrationsPage() {
  const toast = useToast();
  const poll = usePoll<ErpStatusFull>(() => getErpStatus(), 60_000);
  const [testing, setTesting] = useState(false);
  const status = poll.data;

  async function testConnection() {
    setTesting(true);
    const started = performance.now();
    try {
      const fresh = await getErpStatus();
      const ms = Math.round(performance.now() - started);
      poll.reload();
      if (erpIsConnected(fresh)) {
        toast.success(<Bi en={`Odoo answered and the project is ready (${ms} ms).`} ar={`ردّ Odoo والمشروع جاهز (${ms} م.ث).`} />);
      } else {
        toast.warning(<Bi en={fresh.message_en} ar={fresh.message_ar} />);
      }
    } catch {
      toast.error(<Bi en="Could not reach the backend to ask about Odoo." ar="تعذّر الوصول إلى الخادم للاستعلام عن Odoo." />);
    } finally {
      setTesting(false);
    }
  }

  const connected: Card_[] = [
    {
      key: "odoo",
      title: <Bi en="Odoo 17: task system" ar="Odoo 17: نظام المهام" />,
      status: odooStatus(status, poll.loading, !!poll.error && !status),
      permission: "approval",
      reads: (
        <Bi
          en="Employees (for the assignee picker) and the stage of the tasks Xposure created."
          ar="الموظفون (لاختيار المكلَّف) ومرحلة المهام التي أنشأها Xposure."
        />
      ),
      writes: (
        <Bi
          en="One task per action you send to the ERP: the change, clause, suggested action, priority, due date and a link back. Xposure closes that action only when the Odoo task reaches Done; the close is audited and can be undone."
          ar="مهمة واحدة لكل إجراء ترسله إلى نظام ERP: التغيير والبند والإجراء المقترح والأولوية وتاريخ الاستحقاق ورابط العودة. ولا يغلق Xposure ذلك الإجراء إلا حين تصل مهمة Odoo إلى «منجز»، ويُسجَّل الإغلاق ويمكن التراجع عنه."
        />
      ),
      extra: (
        <>
          {status && (
            <p className="int-live" role="status">
              <Bi en={status.message_en} ar={status.message_ar} />
              {status.url && status.reachable && (
                <>
                  {" "}
                  <bdi className="mono">{status.url}</bdi>
                </>
              )}
            </p>
          )}
          <div className="int-actions">
            <Button variant="secondary" size="sm" icon={<Icon icon={RefreshCw} size={14} />} loading={testing} onClick={testConnection}>
              <Bi en="Test connection" ar="اختبار الاتصال" />
            </Button>
            {status?.url && status.reachable && (
              <a className={buttonClass({ variant: "ghost", size: "sm" })} href={status.url} target="_blank" rel="noreferrer">
                <Icon icon={ExternalLink} size={14} />
                <Bi en="Open Odoo" ar="فتح Odoo" />
              </a>
            )}
            <Button variant="link" size="sm" href="/tasks"><Bi en="Go to Tasks" ar="الانتقال إلى المهام" /></Button>
          </div>
        </>
      ),
    },
    {
      key: "exports",
      title: <Bi en="Reports and OSCAL export" ar="التقارير وتصدير OSCAL" />,
      status: { variant: "success", label: <Bi en="Built" ar="مُنجَز" /> },
      permission: "download",
      reads: <Bi en="A change with its clause diff, impacted items and actions." ar="تغيير مع فروقات بنده والعناصر المتأثرة والإجراءات." />,
      writes: (
        <Bi
          en="A PDF report, an Excel worklist or an OSCAL-flavoured JSON file, downloaded by you. It writes to no other system."
          ar="تقرير PDF أو جدول Excel أو ملف JSON بصيغة OSCAL، تنزّله أنت. ولا يكتب في أي نظام آخر."
        />
      ),
      extra: (
        <div className="int-actions">
          <a className={buttonClass({ variant: "secondary", size: "sm" })} href="/api/exports/summary" download>
            <Icon icon={FileText} size={14} />
            <Bi en="Download summary PDF" ar="تنزيل ملخص PDF" />
          </a>
          <Button variant="link" size="sm" href="/changes"><Bi en="Export a single change" ar="تصدير تغيير واحد" /></Button>
        </div>
      ),
    },
    {
      key: "webhooks",
      title: <Bi en="Webhooks" ar="الخطافات (Webhooks)" />,
      status: { variant: "info", label: <Bi en="Optional" ar="اختياري" /> },
      permission: "events",
      reads: <Bi en="Nothing. A receiving endpoint is also built in, for testing." ar="لا شيء. ويوجد أيضًا نقطة استقبال مدمجة للاختبار." />,
      writes: (
        <Bi
          en="Notifications when a change is detected, impact is computed, or an action is approved or delegated, to the URL you configure. Signed when a secret is set. Off until a URL is configured, and a failed delivery never blocks a decision."
          ar="إشعارات عند رصد تغيير أو حساب الأثر أو اعتماد إجراء أو إسناده، إلى العنوان الذي تضبطه. توقَّع عند ضبط سر مشترك. وتبقى متوقفة حتى يُضبط عنوان، ولا يعطّل فشل التسليم أي قرار."
        />
      ),
      extra: (
        <div className="int-actions">
          <Button variant="link" size="sm" href="/settings"><Bi en="See received webhooks in Settings" ar="عرض الخطافات المستلَمة في الإعدادات" /></Button>
        </div>
      ),
    },
    {
      key: "email",
      title: <Bi en="Email notifications" ar="إشعارات البريد الإلكتروني" />,
      status: { variant: "info", label: <Bi en="Optional" ar="اختياري" /> },
      permission: "events",
      reads: <Bi en="Nothing." ar="لا شيء." />,
      writes: (
        <Bi
          en="A message telling the person an action was assigned to what is expected of them. Off unless an SMTP server is configured; a failed delivery never blocks the assignment."
          ar="رسالة تخبر المكلَّف بما هو مطلوب منه عند إسناد إجراء إليه. تبقى متوقفة ما لم يُضبط خادم SMTP، ولا يمنع فشل التسليم عملية الإسناد."
        />
      ),
    },
  ];

  const sources: Card_[] = [
    {
      key: "csv",
      title: <Bi en="NCA self-assessment sheet (CSV)" ar="ورقة التقييم الذاتي لهيئة الأمن السيبراني (CSV)" />,
      status: { variant: "success", label: <Bi en="Built (command line)" ar="مُنجَز (سطر الأوامر)" /> },
      permission: "readonly",
      reads: <Bi en="One row per control: control number, status, owner, evidence reference." ar="صف لكل ضابط: رقم الضابط والحالة والمالك ومرجع الدليل." />,
      writes: <Bi en="Your organization graph: control mappings, owners and evidence, deduplicated." ar="مخطط مؤسستك: ربط الضوابط والملّاك والأدلة دون تكرار." />,
    },
    {
      key: "odoo-data",
      title: <Bi en="Odoo as a data source" ar="Odoo كمصدر بيانات" />,
      status: { variant: "success", label: <Bi en="Built (command line)" ar="مُنجَز (سطر الأوامر)" /> },
      permission: "readonly",
      reads: <Bi en="Products, product lines and suppliers." ar="المنتجات وخطوط المنتجات والموردون." />,
      writes: <Bi en="Nothing in Odoo. Every call is a read; the adapter has no write path." ar="لا شيء في Odoo. كل استدعاء قراءة، ولا يوجد في المحوّل أي مسار كتابة." />,
    },
    {
      key: "sap",
      title: <Bi en="SAP S/4HANA (OData)" ar="SAP S/4HANA (OData)" />,
      status: { variant: "warning", label: <Bi en="Stub" ar="هيكل أولي" /> },
      permission: null,
      reads: <Bi en="Not yet. The response mapping is not written because nobody has looked at a real response." ar="ليس بعد. لم يُكتب ربط الاستجابة لأن أحدًا لم يطّلع بعد على استجابة حقيقية." />,
      writes: <Bi en="Nothing. SAP offers a free public sandbox that would let it be built and tested." ar="لا شيء. وتوفر SAP بيئة تجريبية عامة مجانية تتيح بناءه واختباره." />,
    },
    {
      key: "oracle",
      title: <Bi en="Oracle Fusion" ar="Oracle Fusion" />,
      status: { variant: "warning", label: <Bi en="Blocked" ar="معطَّل" /> },
      permission: null,
      reads: <Bi en="Not possible yet. Fusion applications have no free tier and no public sandbox." ar="غير ممكن بعد. لا توجد لتطبيقات Fusion باقة مجانية ولا بيئة تجريبية عامة." />,
      writes: <Bi en="Nothing. It needs partner access before it can be built or tested." ar="لا شيء. يحتاج إلى وصول عبر شريك قبل أن يمكن بناؤه أو اختباره." />,
    },
  ];

  const planned: Card_[] = [
    {
      key: "grc",
      title: <Bi en="Enterprise GRC register" ar="سجل الحوكمة والمخاطر والامتثال المؤسسي" />,
      status: { variant: "neutral", label: <Bi en="Planned" ar="مخطَّط" /> },
      permission: null,
      reads: <Bi en="Planned: the current control register, to map it against detected clauses." ar="مخطَّط: سجل الضوابط الحالي لمطابقته مع البنود المرصودة." />,
      writes: <Bi en="Nothing today. OSCAL export is the integration point until a connector exists." ar="لا شيء حاليًا. يبقى تصدير OSCAL نقطة التكامل إلى حين وجود موصّل." />,
    },
    {
      key: "idp",
      title: <Bi en="Identity directory (LDAP / SSO)" ar="دليل الهوية (LDAP / SSO)" />,
      status: { variant: "neutral", label: <Bi en="Planned" ar="مخطَّط" /> },
      permission: null,
      reads: <Bi en="Planned: identity, role and group." ar="مخطَّط: الهوية والدور والمجموعة." />,
      writes: <Bi en="Nothing. Today people sign in with Xposure's own accounts." ar="لا شيء. يسجّل المستخدمون الدخول اليوم بحسابات Xposure نفسها." />,
    },
  ];

  return (
    <main className="int">
      <PageHeader
        title={<Bi en="Integrations" ar="التكاملات" />}
        subtitle={
          <Bi
            en="Every connection between Xposure and the systems around it: what it reads, what it writes, and what really exists today. Nothing writes to another system without a person's approval."
            ar="كل اتصال بين Xposure والأنظمة المحيطة به: ما يقرؤه وما يكتبه وما هو موجود فعلًا اليوم. ولا يكتب أي اتصال في نظام آخر دون اعتماد شخص."
          />
        }
      />

      <p className="int-why">
        <Bi
          en="Xposure does not replace your GRC or task system: it feeds them. Detected clauses, decisions and tasks leave through standard files or through a connection you control."
          ar="لا يحلّ Xposure محل نظام الحوكمة أو المهام لديك، بل يغذّيه. تخرج البنود المرصودة والقرارات والمهام عبر ملفات قياسية أو عبر اتصال تتحكم فيه."
        />
      </p>

      <h2 className="int-h"><Bi en="Connected systems" ar="الأنظمة المتصلة" /></h2>
      <div className="int-grid">
        {connected.map((c) => <IntegrationCard key={c.key} c={c} />)}
      </div>

      <h2 className="int-h"><Bi en="Where your organization data can come from" ar="من أين تأتي بيانات مؤسستك" /></h2>
      <div className="int-grid">
        {sources.map((c) => <IntegrationCard key={c.key} c={c} />)}
      </div>

      <h2 className="int-h"><Bi en="Planned" ar="مخطَّط" /></h2>
      <div className="int-grid">
        {planned.map((c) => <IntegrationCard key={c.key} c={c} />)}
      </div>

      <p className="int-foot">
        <Bi
          en="Every write is logged in the audit log under the name of the person who approved it. "
          ar="يُسجَّل كل ما يُكتب في سجل التدقيق باسم الشخص الذي اعتمده. "
        />
        <Link href="/audit"><Bi en="Open the audit log" ar="فتح سجل التدقيق" /></Link>
      </p>
    </main>
  );
}
