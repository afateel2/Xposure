"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { Bot, ClipboardCheck, FileDiff, History, LayoutDashboard, ListChecks, ShieldCheck, UserPlus, Workflow } from "lucide-react";
import { Bi } from "@/components/Bi";
import { Button, Card, Icon, PageHeader } from "@/components/ui";

interface Step {
  icon: typeof Bot;
  title: ReactNode;
  body: ReactNode;
}

/**
 * The guide describes this application as it is today: the screens, button
 * labels and rules below are the real ones (see backend/app/policy.py for the
 * automation rules and backend/app/routes/actions.py for what a decision does).
 */
const FLOW: Step[] = [
  {
    icon: LayoutDashboard,
    title: <Bi en="Start on the Dashboard" ar="ابدأ من لوحة التحكم" />,
    body: (
      <Bi
        en="It shows what the agent is doing, how fresh the data is, and what needs a decision. Nothing on it changes anything."
        ar="تعرض ما يفعله الوكيل ومدى حداثة البيانات وما يحتاج إلى قرار. لا يغيّر أي شيء فيها أي بيانات."
      />
    ),
  },
  {
    icon: Bot,
    title: <Bi en="Press Scan now on Run agent" ar="اضغط «افحص الآن» في تشغيل الوكيل" />,
    body: (
      <Bi
        en="The agent checks the regulator portal, fetches the new edition and runs the pipeline: read and index, match clauses between editions, classify each change, trace impact through your organization, score priority, and apply the automation policy. Starting a scan needs a signed-in account."
        ar="يفحص الوكيل بوابة الجهة التنظيمية ويجلب الإصدار الجديد ويشغّل المسار: قراءة وفهرسة، ومطابقة البنود بين الإصدارين، وتصنيف كل تغيير، وتتبّع الأثر في مؤسستك، وحساب الأولوية، وتطبيق سياسة الأتمتة. يتطلب بدء الفحص حسابًا مسجَّل الدخول."
      />
    ),
  },
  {
    icon: FileDiff,
    title: <Bi en="Open a change from Changes" ar="افتح تغييرًا من صفحة التغييرات" />,
    body: (
      <Bi
        en="The list puts the changes that still need a decision first, ranked by priority. Open one to review it."
        ar="تضع القائمة أولًا التغييرات التي ما زالت تحتاج إلى قرار، مرتبة حسب الأولوية. افتح أحدها لمراجعته."
      />
    ),
  },
  {
    icon: ShieldCheck,
    title: <Bi en="Read the evidence" ar="اقرأ الدليل" />,
    body: (
      <Bi
        en="Read the plain-language summary, the old versus new clause, and the citation check, which confirms with plain code that the text really is in the stored source file. Then read why the change got its priority."
        ar="اقرأ الملخص المبسّط والبند القديم مقابل الجديد وفحص الاستشهاد، الذي يؤكد بالكود أن النص موجود فعلًا في ملف المصدر المحفوظ. ثم اقرأ سبب أولوية التغيير."
      />
    ),
  },
  {
    icon: ClipboardCheck,
    title: <Bi en="Decide each suggested action" ar="اتخذ قرارًا في كل إجراء مقترح" />,
    body: (
      <ul className="guide-list">
        <li>
          <b><Bi en="Let the agent handle it" ar="ترك الوكيل يتولى الأمر" /></b>
          {": "}
          <Bi
            en="the agent edits the mapped company file (a policy, procedure or setting). You see the diff, and Undo restores the earlier version."
            ar="يعدّل الوكيل ملف المنشأة المرتبط (سياسة أو إجراء أو إعداد). ترى الفروقات، ويعيد «تراجع» النسخة السابقة."
          />
        </li>
        <li>
          <b><Bi en="Assign to a person" ar="إسناد إلى شخص" /></b>
          {": "}
          <Bi
            en="send it to someone by name, or choose Send to ERP (Odoo) to create a real task for them."
            ar="أسنده إلى شخص بالاسم، أو اختر «إرسال إلى نظام ERP (Odoo)» لإنشاء مهمة حقيقية له."
          />
        </li>
        <li>
          <b><Bi en="Dismiss" ar="تجاهل" /></b>
          {": "}
          <Bi
            en="no action will be taken. A written reason is required and goes into the audit log under your name."
            ar="لن يُتخذ أي إجراء. السبب المكتوب مطلوب ويُسجَّل في سجل التدقيق باسمك."
          />
        </li>
      </ul>
    ),
  },
  {
    icon: UserPlus,
    title: <Bi en="Close the loop through Odoo" ar="أغلق الحلقة عبر Odoo" />,
    body: (
      <Bi
        en="The assignee gets a task in Odoo and a notification there. When they mark it Done in Odoo, press Sync now on Tasks: the Xposure action closes and the audit log records it. You can undo that close."
        ar="يستلم المكلَّف مهمة في Odoo مع إشعار هناك. عندما يضعها منجزة في Odoo اضغط «مزامنة الآن» في صفحة المهام: يُغلق الإجراء في Xposure ويسجّل سجل التدقيق ذلك، ويمكنك التراجع عن هذا الإغلاق."
      />
    ),
  },
  {
    icon: ListChecks,
    title: <Bi en="Keep moving through the queue" ar="تابع التقدم في الطابور" />,
    body: (
      <Bi
        en="The bar at the bottom of a change shows where it sits in the review queue and how many of its actions are decided. Use Next change, or press j for next and k for previous. It can also move on by itself after your last decision if you switch that on."
        ar="يوضح الشريط أسفل التغيير موقعه في طابور المراجعة وعدد الإجراءات المحسومة فيه. استخدم «التغيير التالي»، أو اضغط j للتالي وk للسابق. ويمكنه أيضًا الانتقال تلقائيًا بعد آخر قرار إذا فعّلت ذلك."
      />
    ),
  },
  {
    icon: History,
    title: <Bi en="Prove it afterwards" ar="أثبت ما جرى لاحقًا" />,
    body: (
      <Bi
        en="Each change has a Timeline tab with everything that happened to it. The Audit log lists every decision with who and when. Each change exports as PDF, Excel and OSCAL JSON."
        ar="لكل تغيير تبويب «الخط الزمني» بكل ما جرى عليه. ويسرد سجل التدقيق كل قرار مع من اتخذه ومتى. ويمكن تصدير كل تغيير بصيغ PDF وExcel وOSCAL JSON."
      />
    ),
  },
];

const RULES: { en: string; ar: string }[] = [
  {
    en: "The agent proposes and a person approves. Only two safe, additive action types (collect evidence, notify owner) can ever run on their own, and only under hard gates in code. Everything else waits for you.",
    ar: "يقترح الوكيل ويعتمد الشخص. لا يمكن أن يعمل ذاتيًا سوى نوعين آمنين وإضافيين من الإجراءات (جمع الأدلة وإشعار المالك)، وبشروط صارمة في الكود. وكل ما عدا ذلك ينتظر قرارك.",
  },
  {
    en: "Every decision is written to an append-only audit log with who made it and when. Nothing is edited or deleted; a correction is a new entry.",
    ar: "يُكتب كل قرار في سجل تدقيق لا يُعدَّل ولا يُحذف منه شيء، مع اسم من اتخذه ووقته. والتصحيح يكون بإدخال جديد.",
  },
  {
    en: "Dismissing always needs a written reason.",
    ar: "التجاهل يتطلب دائمًا سببًا مكتوبًا.",
  },
  {
    en: "Edits to company files are versioned and can be undone. The agent only writes inside its sandbox.",
    ar: "تعديلات ملفات المنشأة مُرقَّمة الإصدارات ويمكن التراجع عنها، ولا يكتب الوكيل إلا داخل بيئته المعزولة.",
  },
  {
    en: "Priority comes from a fixed formula (what kind of change, how much of the organization it reaches, how close its deadline is). The model never produces the number.",
    ar: "تأتي الأولوية من معادلة ثابتة (نوع التغيير، ومدى وصوله إلى المؤسسة، وقرب موعده). ولا ينتج النموذج الرقم أبدًا.",
  },
  {
    en: "When the regulator publishes no deadline, the agent shows none. It never invents one.",
    ar: "عندما لا تنشر الجهة التنظيمية موعدًا، لا يعرض الوكيل أي موعد. فهو لا يخترع موعدًا أبدًا.",
  },
];

export default function HelpPage() {
  return (
    <main className="guide">
      <PageHeader
        title={<Bi en="User guide" ar="دليل الاستخدام" />}
        subtitle={
          <Bi
            en="Two minutes, not a manual: what to do on each screen, and what the agent will never do."
            ar="دقيقتان لا دليل مطوّل: ما تفعله في كل شاشة، وما لن يفعله الوكيل أبدًا."
          />
        }
        actions={
          <Button variant="primary" href="/agent" icon={<Icon icon={Bot} size={16} />}>
            <Bi en="Go to Run agent" ar="انتقل إلى تشغيل الوكيل" />
          </Button>
        }
      />

      <Card as="section" title={<Bi en="Your daily flow" ar="سير عملك اليومي" />} icon={<Icon icon={Workflow} size={18} />}>
        <ol className="guide-steps">
          {FLOW.map((step, i) => (
            <li key={i} className="guide-step">
              <span className="guide-step-num tabular" aria-hidden="true">{i + 1}</span>
              <span className="guide-step-icon" aria-hidden="true"><Icon icon={step.icon} size={18} /></span>
              <div className="guide-step-body">
                <h3>{step.title}</h3>
                <div className="guide-step-text">{step.body}</div>
              </div>
            </li>
          ))}
        </ol>
      </Card>

      <div className="guide-two">
        <Card as="section" title={<Bi en="Who can do what" ar="من يستطيع فعل ماذا" />} icon={<Icon icon={ShieldCheck} size={18} />}>
          <dl className="guide-roles">
            <div>
              <dt><Bi en="Anyone, even signed out" ar="أي شخص، حتى دون تسجيل دخول" /></dt>
              <dd><Bi en="Read the dashboard, changes, reports and the audit log." ar="قراءة لوحة التحكم والتغييرات والتقارير وسجل التدقيق." /></dd>
            </div>
            <div>
              <dt><Bi en="Reviewer (signed in)" ar="مراجِع (مسجَّل الدخول)" /></dt>
              <dd>
                <Bi
                  en="Run a scan; approve, dismiss (with a reason), assign, send to Odoo, mark done, and undo."
                  ar="تشغيل فحص؛ والاعتماد والتجاهل (مع السبب) والإسناد والإرسال إلى Odoo ووضع علامة الإنجاز والتراجع."
                />
              </dd>
            </div>
            <div>
              <dt><Bi en="Admin" ar="مسؤول" /></dt>
              <dd>
                <Bi
                  en="Everything a reviewer can do, plus editing the automation policy in Settings. A change there can only ask for less automation than the built-in gates allow, never more."
                  ar="كل ما يستطيعه المراجِع، إضافة إلى تعديل سياسة الأتمتة في الإعدادات. ولا يمكن لأي تعديل هناك أن يطلب أتمتة أكثر مما تسمح به البوابات المدمجة، بل أقل فقط."
                />
              </dd>
            </div>
          </dl>
        </Card>

        <Card as="section" title={<Bi en="Rules that hold for everyone" ar="قواعد تسري على الجميع" />} icon={<Icon icon={ClipboardCheck} size={18} />}>
          <ul className="guide-rules">
            {RULES.map((r, i) => (
              <li key={i}><Bi en={r.en} ar={r.ar} /></li>
            ))}
          </ul>
        </Card>
      </div>

      <Card as="section" title={<Bi en="Shortcuts" ar="الاختصارات" />}>
        <p className="guide-keys">
          <span><kbd>j</kbd> <Bi en="next change in the queue" ar="التغيير التالي في الطابور" /></span>
          <span><kbd>k</kbd> <Bi en="previous change" ar="التغيير السابق" /></span>
          <span><kbd>Esc</kbd> <Bi en="close a dialog" ar="إغلاق النافذة" /></span>
        </p>
        <p className="xp-muted">
          <Bi
            en="Shortcuts only shorten the path: everything they do is also a visible button. They are ignored while you are typing."
            ar="الاختصارات تختصر الطريق فقط: كل ما تفعله له زر ظاهر أيضًا، وتُتجاهل أثناء الكتابة."
          />
        </p>
      </Card>

      <p className="guide-more">
        <Bi en="Looking for where Xposure can run, or what it connects to? See " ar="تبحث عن أماكن تشغيل Xposure أو ما يتصل به؟ راجع " />
        <Link href="/deployment"><Bi en="Deployment options" ar="خيارات النشر" /></Link>
        <Bi en=" and " ar=" و" />
        <Link href="/integrations"><Bi en="Integrations" ar="التكاملات" /></Link>.
      </p>
    </main>
  );
}
