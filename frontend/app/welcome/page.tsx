"use client";

import "./site.css";
import Link from "next/link";
import type { ReactNode } from "react";
import {
  ArrowRight,
  Calculator,
  CircleCheck,
  ClipboardCheck,
  Cog,
  Braces,
  Factory,
  FileDiff,
  FileSearch,
  Flag,
  GitCompare,
  History,
  Info,
  Network,
  Play,
  Radar,
  Scale,
  ScrollText,
  Server,
  ShieldCheck,
  ShoppingCart,
  Split,
  Target,
  Undo2,
  UserCheck,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";
import { Bi } from "@/components/Bi";
import { Logo } from "@/components/Logo";
import { DemoRequestForm } from "@/components/site/DemoRequestForm";
import { SiteNav } from "@/components/site/SiteNav";
import { Badge, Button, Icon } from "@/components/ui";
import { t, useLang } from "@/lib/lang";

type Bilingual = { en: ReactNode; ar: ReactNode };

/* ---------------------------------------------------------------- content */

const HERO_BADGES: (Bilingual & { icon: LucideIcon })[] = [
  { icon: GitCompare, en: "Clause-level comparison", ar: "مقارنة على مستوى البند" },
  { icon: UserCheck, en: "A person approves every consequential step", ar: "يعتمد إنسانٌ كل خطوة ذات أثر" },
  { icon: Factory, en: "Built for Saudi industrial and defense organizations", ar: "مصمَّم للمؤسسات الصناعية والدفاعية السعودية" },
];

// Real measured numbers from the published NCA documents (ECC-1:2018 to ECC-2:2024).
const RUN_MAX = 233;
const RUN_METRICS: { value: number; en: string; ar: string; material?: boolean }[] = [
  { value: 233, en: "Clauses compared in the new edition", ar: "بنود قورنت في الإصدار الجديد" },
  { value: 208, en: "Changes classified", ar: "تغييرات صُنّفت" },
  { value: 93, en: "Judged material", ar: "تغييرات عُدّت جوهرية", material: true },
];

const COMPARE: { icon: LucideIcon; step: Bilingual; today: Bilingual; now: Bilingual }[] = [
  {
    icon: Radar,
    step: { en: "Notice", ar: "الرصد" },
    today: { en: "Someone happens to see that a new edition exists", ar: "يلاحظ شخصٌ بالصدفة أن إصدارًا جديدًا قد صدر" },
    now: {
      en: "The agent checks the source and detects a new edition by its file hash",
      ar: <>يفحص الوكيل المصدر ويكتشف الإصدار الجديد من خلال بصمة الملف (<bdi>hash</bdi>)</>,
    },
  },
  {
    icon: GitCompare,
    step: { en: "Compare", ar: "المقارنة" },
    today: { en: "Two PDFs read side by side, for days", ar: <>قراءة ملفَّي <bdi>PDF</bdi> جنبًا إلى جنب لأيام</> },
    now: {
      en: "Clause-by-clause comparison by code; the model only labels the kind of change",
      ar: "مقارنة بندًا ببند تتم برمجيًا، ويكتفي النموذج بتصنيف نوع التغيير",
    },
  },
  {
    icon: Network,
    step: { en: "Assess impact", ar: "تقدير الأثر" },
    today: { en: "From memory and a spreadsheet", ar: "من الذاكرة ومن جدول بيانات" },
    now: {
      en: "Traced through your own graph of policies, processes, systems and owners",
      ar: "يُتتبَّع الأثر عبر شبكة العلاقات الخاصة بمؤسستك بين السياسات والعمليات والأنظمة والمسؤولين",
    },
  },
  {
    icon: ClipboardCheck,
    step: { en: "Act", ar: "التنفيذ" },
    today: { en: "Tasks by email, documents edited by hand", ar: "مهام عبر البريد الإلكتروني ووثائق تُعدَّل يدويًا" },
    now: {
      en: "Ranked actions; a person approves; the agent edits files (undoable) or creates a task in your ERP",
      ar: <>إجراءات مرتّبة؛ يعتمدها شخص؛ ثم يعدّل الوكيل الملفات (مع إمكانية التراجع) أو ينشئ مهمة في نظام <bdi>ERP</bdi> لديك</>,
    },
  },
  {
    icon: ScrollText,
    step: { en: "Prove", ar: "الإثبات" },
    today: { en: "Evidence rebuilt before the audit", ar: "تُعاد صياغة الأدلة قبل التدقيق" },
    now: {
      en: "An append-only audit trail and exports (PDF, Excel, OSCAL)",
      ar: <>سجل تدقيق يقبل الإضافة فقط، وتصدير إلى <bdi>PDF</bdi> و<bdi>Excel</bdi> و<bdi>OSCAL</bdi></>,
    },
  },
];

const PAINS: { icon: LucideIcon; title: Bilingual; body: Bilingual }[] = [
  {
    icon: Users,
    title: { en: "One change, many owners", ar: "تغيير واحد وجهات كثيرة معنية" },
    body: {
      en: "NCA's control 1-2-2 now requires all cybersecurity positions to be filled by full-time, qualified Saudi professionals: that reaches HR and legal, not only IT.",
      ar: <>يشترط الضابط <bdi>1-2-2</bdi> من <bdi>NCA</bdi> الآن أن تشغل جميع وظائف الأمن السيبراني كوادر سعودية مؤهلة تعمل بدوام كامل، وهذا يمتد إلى الموارد البشرية والشؤون القانونية، لا إلى تقنية المعلومات وحدها.</>,
    },
  },
  {
    icon: FileDiff,
    title: { en: "Official change lists are summaries", ar: "قوائم التغييرات الرسمية مجرد ملخصات" },
    body: {
      en: "ECC-2:2024 lists 17 updates; a clause-level comparison finds more differences to check.",
      ar: <>تذكر <bdi>ECC-2:2024</bdi> <bdi>17</bdi> تحديثًا، والمقارنة على مستوى البند تكشف فروقًا أخرى تستحق الفحص.</>,
    },
  },
  {
    icon: Split,
    title: { en: "Knowing what changed is not knowing what to do", ar: "معرفة ما تغيّر لا تعني معرفة ما يجب فعله" },
    body: {
      en: "The regulation and your policies, systems and owners live in different places.",
      ar: "النظام التنظيمي وسياساتك وأنظمتك والمسؤولون عنها موجودون في أماكن متفرقة.",
    },
  },
  {
    icon: History,
    title: { en: "No trail of who decided what and why", ar: "لا سجلّ يبيّن من قرّر ماذا ولماذا" },
    body: {
      en: "Audit evidence is rebuilt from email and memory.",
      ar: "يُعاد بناء أدلة التدقيق من البريد الإلكتروني ومن الذاكرة.",
    },
  },
];

const STEPS: { title: Bilingual; body: Bilingual }[] = [
  {
    title: { en: "Detect", ar: "الرصد" },
    body: {
      en: "Finds a new edition and reads it into a versioned, clause-by-clause store.",
      ar: "يكتشف الإصدار الجديد ويقرؤه في مخزن يحفظ الإصدارات بندًا ببند.",
    },
  },
  {
    title: { en: "Compare", ar: "المقارنة" },
    body: {
      en: "Aligns the two editions by code and shows the exact sentences that changed.",
      ar: "يطابق الإصدارين برمجيًا ويعرض الجمل التي تغيّرت بالضبط.",
    },
  },
  {
    title: { en: "Trace impact", ar: "تتبّع الأثر" },
    body: {
      en: "Follows each change through your policies, processes, systems, products and owners.",
      ar: "يتتبّع كل تغيير عبر سياساتك وعملياتك وأنظمتك ومنتجاتك والمسؤولين عنها.",
    },
  },
  {
    title: { en: "Prioritize", ar: "ترتيب الأولوية" },
    body: {
      en: "A fixed, explainable score, never the model's opinion.",
      ar: "درجة ثابتة يمكن تفسيرها، وليست رأي النموذج.",
    },
  },
  {
    title: { en: "Decide", ar: "القرار" },
    body: {
      en: "A person approves, assigns or dismisses, with a written reason.",
      ar: "يعتمد شخصٌ الإجراء أو يُسنده أو يستبعده، مع بيان السبب كتابةً.",
    },
  },
  {
    title: { en: "Act and prove", ar: "التنفيذ والإثبات" },
    body: {
      en: "The agent edits files you can undo, or creates a real task in your ERP; every step is in the audit log.",
      ar: <>يعدّل الوكيل ملفات يمكنك التراجع عنها، أو ينشئ مهمة فعلية في نظام <bdi>ERP</bdi> لديك؛ وكل خطوة مسجّلة في سجل التدقيق.</>,
    },
  },
];

const ROLES: { icon: LucideIcon; title: Bilingual; body: Bilingual }[] = [
  {
    icon: ClipboardCheck,
    title: { en: "Compliance officer", ar: "مسؤول الامتثال" },
    body: { en: "One ranked list with evidence for the auditor.", ar: "قائمة واحدة مرتّبة مع الأدلة التي يحتاجها المدقّق." },
  },
  {
    icon: ShieldCheck,
    title: { en: "IT security lead", ar: "مسؤول أمن تقنية المعلومات" },
    body: { en: "Which controls, systems and procedures to change.", ar: "أي الضوابط والأنظمة والإجراءات يجب تغييرها." },
  },
  {
    icon: Cog,
    title: { en: "OT engineering lead", ar: <>مسؤول هندسة التقنيات التشغيلية (<bdi>OT</bdi>)</> },
    body: {
      en: "Which plant and control-system settings are touched, without unreviewed changes.",
      ar: "أي إعدادات في المنشأة وأنظمة التحكم يمسّها التغيير، دون أي تغيير لم يُراجَع.",
    },
  },
  {
    icon: Factory,
    title: { en: "Operations manager", ar: "مدير العمليات" },
    body: { en: "What changes in daily operation.", ar: "ما الذي يتغيّر في التشغيل اليومي." },
  },
  {
    icon: Scale,
    title: { en: "Legal counsel", ar: "المستشار القانوني" },
    body: {
      en: "Which obligations are new, which were withdrawn, who accepted each.",
      ar: "أي الالتزامات جديدة وأيها سُحبت، ومن قَبِل كلًّا منها.",
    },
  },
  {
    icon: ShoppingCart,
    title: { en: "Procurement lead", ar: "مسؤول المشتريات" },
    body: { en: "Which supplier and contract terms are affected.", ar: "أي شروط الموردين والعقود تتأثر." },
  },
];

const TRUST: { icon: LucideIcon; title: Bilingual; body: Bilingual; deployment?: boolean }[] = [
  {
    icon: UserCheck,
    title: { en: "A person approves", ar: "إنسانٌ يعتمد" },
    body: {
      en: "Only two safe, additive action types can ever run on their own, under hard gates in code.",
      ar: "لا يمكن أن ينفَّذ تلقائيًا إلا نوعان فقط من الإجراءات الآمنة التي تقتصر على الإضافة، وتحكمهما بوابات صارمة في الشيفرة.",
    },
  },
  {
    icon: Braces,
    title: { en: "Code finds the facts", ar: "الشيفرة هي التي تجد الوقائع" },
    body: {
      en: "Alignment, differences and graph tracing are deterministic; the model only labels a change code already found.",
      ar: "المطابقة والفروق وتتبّع الأثر في شبكة العلاقات كلها حتمية؛ ولا يقتصر دور النموذج إلا على تصنيف تغيير سبق أن وجدته الشيفرة.",
    },
  },
  {
    icon: Calculator,
    title: { en: "A fixed, explainable priority", ar: "أولوية ثابتة يمكن تفسيرها" },
    body: {
      en: "The score comes from change type, reach and deadline; you can see the arithmetic.",
      ar: "تُحسب الدرجة من نوع التغيير ومداه والموعد النهائي، ويمكنك الاطلاع على العملية الحسابية.",
    },
  },
  {
    icon: Undo2,
    title: { en: "Reversible writes", ar: "كتابة قابلة للتراجع" },
    body: {
      en: "Edits to company files are versioned and can be undone.",
      ar: "تُحفظ تعديلات ملفات الشركة بإصدارات ويمكن التراجع عنها.",
    },
  },
  {
    icon: ScrollText,
    title: { en: "An append-only audit log", ar: "سجل تدقيق يقبل الإضافة فقط" },
    body: {
      en: "Who decided what, when, and why; nothing edited or deleted.",
      ar: "من قرّر ماذا، ومتى، ولماذا؛ دون تعديل أو حذف لأي شيء.",
    },
  },
  {
    icon: Server,
    title: { en: "Built to run inside your perimeter", ar: "مصمَّم للعمل داخل نطاق مؤسستك" },
    body: {
      en: "Designed for on-premises with a local model; see Deployment options for exactly what exists today.",
      ar: "مصمَّم للتشغيل داخل المؤسسة مع نموذج محلي؛ راجع خيارات النشر لمعرفة ما هو متوفر اليوم بدقة.",
    },
    deployment: true,
  },
];

const GOALS: Bilingual[] = [
  {
    en: "At least 95% classification accuracy on 300 or more expert-checked clause pairs",
    ar: <>دقة تصنيف لا تقل عن <bdi>95%</bdi> على <bdi>300</bdi> زوج أو أكثر من البنود التي راجعها خبراء</>,
  },
  {
    en: "Every update the regulator itself lists is detected",
    ar: "رصد كل تحديث تدرجه الجهة المنظِّمة نفسها",
  },
  {
    en: "A ranked worklist from a new edition in minutes",
    ar: "قائمة عمل مرتّبة من إصدار جديد خلال دقائق",
  },
  {
    en: "At least 70% less analyst effort per update, measured in pilots",
    ar: <>خفض جهد المحلل لكل تحديث بنسبة لا تقل عن <bdi>70%</bdi>، وتُقاس في المشاريع التجريبية</>,
  },
];

const PRINCIPLES: { icon: LucideIcon; title: Bilingual; body: Bilingual }[] = [
  {
    icon: FileSearch,
    title: { en: "Evidence over claims", ar: "الدليل قبل الادعاء" },
    body: {
      en: "The numbers here come from a real run, and proposed targets are labeled as targets.",
      ar: "الأرقام هنا مأخوذة من تشغيل فعلي، والأهداف المقترحة موسومة بأنها أهداف.",
    },
  },
  {
    icon: UserCheck,
    title: { en: "People decide", ar: "الناس هم من يقرّرون" },
    body: {
      en: "A person approves every consequential step; the agent prepares the work.",
      ar: "يعتمد إنسانٌ كل خطوة ذات أثر، ويكتفي الوكيل بتجهيز العمل.",
    },
  },
  {
    icon: Flag,
    title: { en: "We say what we have not built", ar: "نذكر ما لم نبنِه بعد" },
    body: {
      en: "Where something is a target or not yet available, we say so instead of implying it works.",
      ar: "حين يكون أمر ما هدفًا أو غير متاح بعد، نقول ذلك بدل أن نوحي بأنه يعمل.",
    },
  },
];

/* ------------------------------------------------------------- components */

function SectionHead({ id, title }: { id: string; title: ReactNode }) {
  return (
    <div className="site-head">
      <h2 className="site-h2" id={id}>
        {title}
      </h2>
    </div>
  );
}

/* ------------------------------------------------------------------- page */

export default function WelcomePage() {
  const lang = useLang();

  return (
    <div className="site-page">
      <a className="site-skip" href="#main">
        <Bi en="Skip to main content" ar="تخطَّ إلى المحتوى الرئيسي" />
      </a>
      <SiteNav />

      <main id="main">
        {/* HERO */}
        <section id="top" className="site-hero" aria-labelledby="hero-title">
          <div className="site-wrap site-hero-grid">
            <div>
              <p className="site-eyebrow">
                <Bi en="Regulatory change, handled" ar="التغيّر التنظيمي، تحت السيطرة" />
              </p>
              <h1 className="site-hero-title" id="hero-title">
                <Bi
                  en="An AI agent that watches regulations, finds exactly what changed, and helps your team act on it"
                  ar="وكيل ذكي يراقب الأنظمة، ويحدّد ما تغيّر بالضبط، ويساعد فريقك على التصرف"
                />
              </h1>
              <p className="site-lead">
                <Bi
                  en="Xposure compares each new edition of a regulation with the last one, clause by clause, traces what it touches inside your organization, ranks the work, and routes it to the right person. A human approves every consequential step."
                  ar={<>يقارن <bdi>Xposure</bdi> كل إصدار جديد من النظام بالسابق بندًا ببند، ويتتبّع ما يمسّه داخل مؤسستك، ويرتّب العمل، ويوجّهه إلى الشخص المناسب. ويعتمد إنسانٌ كل خطوة ذات أثر.</>}
                />
              </p>
              <div className="site-hero-actions">
                <Button href="/" variant="primary" size="lg" icon={<Icon icon={Play} size={16} />}>
                  <Bi en="Open the live demo" ar="افتح العرض المباشر" />
                </Button>
                <Button href="#demo" variant="secondary" size="lg">
                  <Bi en="Request a demo" ar="اطلب عرضًا توضيحيًا" />
                </Button>
              </div>
              <ul className="site-badges">
                {HERO_BADGES.map((b, i) => (
                  <li key={i}>
                    <Badge variant="neutral" className="site-badge">
                      <Icon icon={b.icon} size={14} />
                      <Bi en={b.en} ar={b.ar} />
                    </Badge>
                  </li>
                ))}
              </ul>
            </div>

            <aside className="site-run" aria-labelledby="run-title">
              <div className="site-run-head">
                <span className="site-card-icon">
                  <Icon icon={GitCompare} size={20} />
                </span>
                <div>
                  <p className="site-run-title" id="run-title">
                    <Bi en="Example run" ar="مثال على تشغيل فعلي" />
                  </p>
                  <p className="site-run-sub">
                    <Bi
                      en={<><span className="site-mono">ECC-1:2018</span> to <span className="site-mono">ECC-2:2024</span></>}
                      ar={<>من <bdi className="site-mono">ECC-1:2018</bdi> إلى <bdi className="site-mono">ECC-2:2024</bdi></>}
                    />
                  </p>
                </div>
              </div>
              <ul className="site-metrics">
                {RUN_METRICS.map((m) => (
                  <li className="site-metric" key={m.value}>
                    <span className="site-metric-num">{m.value}</span>
                    <span className="site-metric-label">
                      <Bi en={m.en} ar={m.ar} />
                    </span>
                    <span className="site-metric-bar" aria-hidden="true">
                      <i className={m.material ? "is-material" : undefined} style={{ inlineSize: `${(m.value / RUN_MAX) * 100}%` }} />
                    </span>
                  </li>
                ))}
              </ul>
              <p className="site-run-caption">
                <Bi
                  en="From a real run on the published NCA Essential Cybersecurity Controls. The demo company is fictional."
                  ar={<>من تشغيل فعلي على الضوابط الأساسية للأمن السيبراني المنشورة من الهيئة الوطنية للأمن السيبراني (<bdi>NCA</bdi>). الشركة المستخدمة في العرض افتراضية.</>}
                />
              </p>
            </aside>
          </div>
        </section>

        {/* PROBLEM */}
        <section id="problem" className="site-section site-section-alt" aria-labelledby="problem-title">
          <div className="site-wrap">
            <SectionHead
              id="problem-title"
              title={<Bi en="Keeping up with regulatory change is still manual" ar="مواكبة التغيّر التنظيمي ما زالت يدوية" />}
            />
            <div className="site-cmp">
              <div className="site-cmp-head" aria-hidden="true">
                <span />
                <span>
                  <Bi en="Today" ar="اليوم" />
                </span>
                <span>
                  <Bi en="With Xposure" ar={<>مع <bdi>Xposure</bdi></>} />
                </span>
              </div>
              <ol className="site-cmp-list">
                {COMPARE.map((row, i) => (
                  <li className="site-cmp-row" key={i}>
                    <h3 className="site-cmp-step">
                      <Icon icon={row.icon} size={18} />
                      <span>
                        <Bi en={row.step.en} ar={row.step.ar} />
                      </span>
                    </h3>
                    <div className="site-cmp-cell site-cmp-today">
                      <Icon icon={X} size={16} />
                      <div className="site-cmp-body">
                        <span className="site-cmp-tag">
                          <Bi en="Today" ar="اليوم" />
                        </span>
                        <Bi en={row.today.en} ar={row.today.ar} />
                      </div>
                    </div>
                    <div className="site-cmp-cell site-cmp-now">
                      <Icon icon={CircleCheck} size={16} />
                      <div className="site-cmp-body">
                        <span className="site-cmp-tag">
                          <Bi en="With Xposure" ar={<>مع <bdi>Xposure</bdi></>} />
                        </span>
                        <Bi en={row.now.en} ar={row.now.ar} />
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
            </div>

            <ul className="site-grid site-grid-2 site-pains">
              {PAINS.map((p, i) => (
                <li className="site-card site-card-pain" key={i}>
                  <span className="site-card-icon">
                    <Icon icon={p.icon} size={20} />
                  </span>
                  <h3>
                    <Bi en={p.title.en} ar={p.title.ar} />
                  </h3>
                  <p>
                    <Bi en={p.body.en} ar={p.body.ar} />
                  </p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* HOW IT WORKS */}
        <section id="how" className="site-section" aria-labelledby="how-title">
          <div className="site-wrap">
            <SectionHead id="how-title" title={<Bi en="How Xposure works" ar={<>كيف يعمل <bdi>Xposure</bdi></>} />} />
            <ol className="site-grid site-grid-3">
              {STEPS.map((s, i) => (
                <li className="site-card" key={i}>
                  <div className="site-step-head">
                    <span className="site-step-num" aria-hidden="true">
                      {i + 1}
                    </span>
                    <h3>
                      <Bi en={s.title.en} ar={s.title.ar} />
                    </h3>
                  </div>
                  <p>
                    <Bi en={s.body.en} ar={s.body.ar} />
                  </p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* WHO IT IS FOR */}
        <section id="roles" className="site-section site-section-alt" aria-labelledby="roles-title">
          <div className="site-wrap">
            <SectionHead id="roles-title" title={<Bi en="Who it is for" ar="لمن هو" />} />
            <ul className="site-grid site-grid-3">
              {ROLES.map((r, i) => (
                <li className="site-card" key={i}>
                  <span className="site-card-icon">
                    <Icon icon={r.icon} size={20} />
                  </span>
                  <h3>
                    <Bi en={r.title.en} ar={r.title.ar} />
                  </h3>
                  <p>
                    <Bi en={r.body.en} ar={r.body.ar} />
                  </p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* TRUST */}
        <section id="trust" className="site-section" aria-labelledby="trust-title">
          <div className="site-wrap">
            <SectionHead id="trust-title" title={<Bi en="Built to be checked" ar="مصمَّم ليُراجَع" />} />
            <ul className="site-grid site-grid-3">
              {TRUST.map((item, i) => (
                <li className="site-card" key={i}>
                  <span className="site-card-icon">
                    <Icon icon={item.icon} size={20} />
                  </span>
                  <h3>
                    <Bi en={item.title.en} ar={item.title.ar} />
                  </h3>
                  <p>
                    <Bi en={item.body.en} ar={item.body.ar} />
                  </p>
                  {item.deployment ? (
                    <Link href="/deployment" className="site-link">
                      <Bi en="Deployment options" ar="خيارات النشر" />
                      <Icon icon={ArrowRight} size={16} flipRtl />
                    </Link>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* GOALS */}
        <section id="goals" className="site-section site-section-alt" aria-labelledby="goals-title">
          <div className="site-wrap">
            <SectionHead id="goals-title" title={<Bi en="What we are working toward" ar="ما نعمل على تحقيقه" />} />
            <p className="site-note site-goals-note">
              <Icon icon={Info} size={18} />
              <span>
                <Bi en="These are proposed targets, not results." ar="هذه أهداف مقترحة، وليست نتائج." />
              </span>
            </p>
            <ul className="site-grid site-grid-2">
              {GOALS.map((g, i) => (
                <li className="site-card" key={i}>
                  <div className="site-goal-top">
                    <span className="site-card-icon">
                      <Icon icon={Target} size={20} />
                    </span>
                    <Badge variant="warning">
                      <Bi en="Proposed target" ar="هدف مقترح" />
                    </Badge>
                  </div>
                  <p className="site-goal-text">
                    <Bi en={g.en} ar={g.ar} />
                  </p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* ABOUT */}
        <section id="about" className="site-section" aria-labelledby="about-title">
          <div className="site-wrap">
            <SectionHead id="about-title" title={<Bi en="About Xposure" ar={<>عن <bdi>Xposure</bdi></>} />} />
            <div className="site-about">
              <div className="site-about-text">
                <p>
                  <Bi
                    en="Xposure starts from one question: when a regulator publishes a new edition, how does an organization learn, in hours instead of weeks, exactly what changed and who must act?"
                    ar={<>ينطلق <bdi>Xposure</bdi> من سؤال واحد: حين تنشر الجهة المنظِّمة إصدارًا جديدًا، كيف تعرف المؤسسة خلال ساعات لا أسابيع ما الذي تغيّر بالضبط ومن يجب أن يتحرك؟</>}
                  />
                </p>
                <p>
                  <Bi
                    en="It is built for Saudi industrial and defense organizations, where a missed change carries compliance, contractual and national-security weight."
                    ar="وهو مصمَّم للمؤسسات الصناعية والدفاعية السعودية، حيث يحمل أي تغيير فائت ثقلًا من حيث الامتثال والالتزامات التعاقدية والأمن الوطني."
                  />
                </p>
              </div>
              <ul className="site-principles">
                {PRINCIPLES.map((p, i) => (
                  <li className="site-principle" key={i}>
                    <span className="site-card-icon">
                      <Icon icon={p.icon} size={20} />
                    </span>
                    <div>
                      <h3>
                        <Bi en={p.title.en} ar={p.title.ar} />
                      </h3>
                      <p>
                        <Bi en={p.body.en} ar={p.body.ar} />
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        {/* REQUEST A DEMO */}
        <section id="demo" className="site-section site-section-alt" aria-labelledby="demo-title">
          <div className="site-wrap">
            <div className="site-demo-head">
              <h2 className="site-h2" id="demo-title">
                <Bi en="Request a demo" ar="اطلب عرضًا توضيحيًا" />
              </h2>
              <p className="site-note site-note-info">
                <Icon icon={Info} size={18} />
                <span>
                  <Bi
                    en="This form is a prototype and does not send your details anywhere."
                    ar="هذا النموذج تجريبي ولا يرسل بياناتك إلى أي جهة."
                  />
                </span>
              </p>
            </div>
            <div className="site-form-card">
              <DemoRequestForm labelledBy="demo-title" />
            </div>
          </div>
        </section>
      </main>

      {/* FOOTER */}
      <footer className="site-footer">
        <div className="site-wrap">
          <div className="site-footer-top">
            <div className="site-footer-brand">
              <Logo size={30} />
              <p>
                <Bi
                  en="Regulatory change monitoring for Saudi industrial and defense organizations"
                  ar="مراقبة التغيّر التنظيمي للمؤسسات الصناعية والدفاعية السعودية"
                />
              </p>
            </div>
            <nav aria-label={t(lang, "Footer", "التذييل")}>
              <ul className="site-footer-links">
                <li>
                  <Link href="/help">
                    <Bi en="User guide" ar="دليل المستخدم" />
                  </Link>
                </li>
                <li>
                  <Link href="/deployment">
                    <Bi en="Deployment options" ar="خيارات النشر" />
                  </Link>
                </li>
                <li>
                  <Link href="/">
                    <Bi en="Open the live demo" ar="افتح العرض المباشر" />
                  </Link>
                </li>
              </ul>
            </nav>
          </div>
          <p className="site-footer-demo">
            <Bi
              en="Demo data: Eastern Industrial Company is a fictional company."
              ar="بيانات العرض: الشركة الصناعية الشرقية شركة افتراضية."
            />
          </p>
        </div>
      </footer>
    </div>
  );
}
