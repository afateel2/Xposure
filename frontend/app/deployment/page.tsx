"use client";

import type { ReactNode } from "react";
import { Building, Cloud, Layers, Server, ShieldCheck } from "lucide-react";
import { Bi } from "@/components/Bi";
import { Badge, Card, Icon, PageHeader } from "@/components/ui";

interface Option {
  key: string;
  icon: typeof Server;
  title: ReactNode;
  status: { variant: "info" | "neutral"; label: ReactNode };
  body: ReactNode;
  points: ReactNode[];
  state: ReactNode;
}

/**
 * Honest by construction: each option carries a status. "Target configuration"
 * means the product is designed around it and the stack runs today on one
 * machine; "Planned" means it is neither built nor tested yet. No prices here:
 * where Xposure runs is a technical and regulatory choice that comes first.
 */
const OPTIONS: Option[] = [
  {
    key: "onprem",
    icon: Building,
    title: <Bi en="On-premises" ar="داخل المنشأة" />,
    status: { variant: "info", label: <Bi en="Target configuration" ar="التهيئة المستهدفة" /> },
    body: (
      <Bi
        en="Runs on your own servers inside your network. This is the configuration Xposure is designed around for defense and government-linked organizations."
        ar="يعمل على خوادمك داخل شبكتك. هذه هي التهيئة التي صُمّم Xposure حولها للجهات الدفاعية والمرتبطة بالجهات الحكومية."
      />
    ),
    points: [
      <Bi key="a" en="The database, the vector index, the documents and the logs all stay inside your perimeter." ar="تبقى قاعدة البيانات وفهرس المتجهات والوثائق والسجلات كلها داخل محيطك." />,
      <Bi key="b" en="The language model runs locally through Ollama, so no clause text, policy or organization data goes to an outside AI service." ar="يعمل النموذج اللغوي محليًا عبر Ollama، فلا يخرج نص بند أو سياسة أو بيانات منشأة إلى أي خدمة ذكاء اصطناعي خارجية." />,
      <Bi key="c" en="The only outbound access needed is to fetch publicly published regulator documents." ar="الاتصال الخارجي الوحيد المطلوب هو جلب وثائق الجهات التنظيمية المنشورة علنًا." />,
    ],
    state: (
      <Bi
        en="Status: the whole stack runs today on a single machine. Development and benchmarking currently use a hosted model; the benchmark that confirms accuracy and speed with a local model on your hardware is still to be done."
        ar="الحالة: تعمل الحزمة كاملة اليوم على جهاز واحد. يعتمد التطوير والقياس حاليًا على نموذج مستضاف؛ أما قياس الدقة والسرعة بنموذج محلي على عتادك فلم يُنجز بعد."
      />
    ),
  },
  {
    key: "cloud",
    icon: Cloud,
    title: <Bi en="Local cloud (in-Kingdom)" ar="سحابة محلية (داخل المملكة)" />,
    status: { variant: "neutral", label: <Bi en="Planned" ar="مخطَّط" /> },
    body: (
      <Bi
        en="The same stack in a dedicated tenant of an approved cloud provider hosted in the Kingdom, for organizations that have no data centre of their own."
        ar="الحزمة نفسها في مستأجر مخصص لدى مزوّد سحابي معتمد داخل المملكة، للمنشآت التي لا تملك مركز بيانات خاصًا بها."
      />
    ),
    points: [
      <Bi key="a" en="One isolated tenant per customer, with no shared compute." ar="مستأجر معزول لكل عميل دون موارد حوسبة مشتركة." />,
      <Bi key="b" en="The models run in that same tenant, not behind a shared external API." ar="تعمل النماذج في المستأجر نفسه لا خلف واجهة برمجة خارجية مشتركة." />,
      <Bi key="c" en="The hosting location is written into the contract." ar="يُكتب موقع الاستضافة في العقد." />,
    ],
    state: (
      <Bi
        en="Status: planned. It has not been deployed or tested on a cloud provider yet."
        ar="الحالة: مخطَّط. لم يُنشر بعد على أي مزوّد سحابي ولم يُختبر."
      />
    ),
  },
  {
    key: "group",
    icon: Layers,
    title: <Bi en="Multi-company group" ar="مجموعة شركات" />,
    status: { variant: "neutral", label: <Bi en="Planned" ar="مخطَّط" /> },
    body: (
      <Bi
        en="One instance serving several companies in a group, each with its own data, users and audit log, plus a consolidated group-level view."
        ar="نسخة واحدة تخدم عدة شركات في مجموعة، لكل منها بياناتها ومستخدموها وسجل تدقيقها، مع عرض موحّد على مستوى المجموعة."
      />
    ),
    points: [
      <Bi key="a" en="Each company's data is kept apart from the others." ar="تُفصل بيانات كل شركة عن الأخريات." />,
      <Bi key="b" en="Regulatory sources can be shared where they match and separated where they differ." ar="يمكن مشاركة المصادر التنظيمية حيث تتطابق وفصلها حيث تختلف." />,
      <Bi key="c" en="A group-level compliance report next to one per company." ar="تقرير امتثال على مستوى المجموعة إلى جانب تقرير لكل شركة." />,
    ],
    state: (
      <Bi
        en="Status: planned. The current build serves one organization."
        ar="الحالة: مخطَّط. النسخة الحالية تخدم مؤسسة واحدة."
      />
    ),
  },
];

export default function DeploymentPage() {
  return (
    <main className="dep">
      <PageHeader
        title={<Bi en="Deployment options" ar="خيارات النشر" />}
        subtitle={
          <Bi
            en="Where Xposure runs, and who owns the hardware and the data in each option. The features are the same everywhere; what differs is the network boundary."
            ar="أين يعمل Xposure، ومن يملك العتاد والبيانات في كل خيار. الميزات واحدة في كل مكان؛ ما يختلف هو حدود الشبكة."
          />
        }
      />

      <div className="dep-grid">
        {OPTIONS.map((o) => (
          <Card
            key={o.key}
            as="article"
            className="dep-card"
            title={o.title}
            icon={<Icon icon={o.icon} size={18} />}
            actions={<Badge variant={o.status.variant}>{o.status.label}</Badge>}
          >
            <p className="dep-body">{o.body}</p>
            <ul className="dep-points">
              {o.points.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
            <p className="dep-state">{o.state}</p>
          </Card>
        ))}
      </div>

      <div className="dep-two">
        <Card as="section" title={<Bi en="What it takes to run" ar="ما يلزم للتشغيل" />} icon={<Icon icon={Server} size={18} />}>
          <ul className="dep-points">
            <li><Bi en="Docker for PostgreSQL 16 and the Qdrant vector index (Odoo 17 is an optional extra for the demo ERP)." ar="Docker لتشغيل PostgreSQL 16 وفهرس المتجهات Qdrant (ويُعدّ Odoo 17 إضافة اختيارية لنظام ERP التجريبي)." /></li>
            <li><Bi en="Python 3.12 or newer for the backend and Node.js 18 or newer for the web app." ar="Python 3.12 أو أحدث للخلفية، وNode.js 18 أو أحدث لتطبيق الويب." /></li>
            <li>
              <Bi
                en="For a local language model, a GPU server. Models in the 27 to 31 billion parameter class are expected to need roughly 24 to 48 GB of GPU memory (an estimate, to be confirmed by the local benchmark). A 12 GB GPU is not enough at a usable speed."
                ar="لتشغيل نموذج لغوي محلي يلزم خادم بمعالج رسومات. يُتوقع أن تحتاج نماذج بحجم 27 إلى 31 مليار معامل إلى ما بين 24 و48 غيغابايت تقريبًا من ذاكرة المعالج الرسومي (تقدير يؤكده القياس المحلي). ولا تكفي بطاقة بسعة 12 غيغابايت لسرعة مقبولة."
              />
            </li>
            <li><Bi en="Outbound access to publicly published regulator pages only (plus a hosted model endpoint if you choose one instead of a local model)." ar="اتصال خارجي بصفحات الجهات التنظيمية المنشورة علنًا فقط (إضافة إلى نقطة نموذج مستضاف إن اخترته بدل النموذج المحلي)." /></li>
          </ul>
        </Card>

        <Card as="section" title={<Bi en="Be clear about today's development setup" ar="للوضوح: إعداد التطوير الحالي" />} icon={<Icon icon={ShieldCheck} size={18} />}>
          <p className="dep-body">
            <Bi
              en="While the local-model benchmark is pending, development runs against a hosted model. In that setup the text of regulation clauses and the generated summaries are sent to the model provider. Only public regulator text and a fictional demo company are involved. It is a development setting, not the on-premises configuration above."
              ar="إلى حين إنجاز قياس النموذج المحلي، يعمل التطوير على نموذج مستضاف. في هذا الإعداد تُرسل نصوص بنود الأنظمة والملخصات المولَّدة إلى مزوّد النموذج، ولا يشمل ذلك سوى نصوص تنظيمية منشورة علنًا وشركة تجريبية افتراضية. هذا إعداد تطوير لا التهيئة المحلية المذكورة أعلاه."
            />
          </p>
          <p className="dep-body">
            <Bi
              en="Customers linked to government or critical infrastructure often require in-Kingdom hosting by contract, even where no law demands it. That is why the on-premises option comes first."
              ar="كثيرًا ما تشترط الجهات المرتبطة بالقطاع الحكومي أو البنية التحتية الحرجة الاستضافة داخل المملكة بموجب العقد، حتى حين لا يوجب ذلك نظام. ولهذا يأتي خيار التشغيل داخل المنشأة أولًا."
            />
          </p>
        </Card>
      </div>

      <p className="dep-foot">
        <Bi
          en="No prices on this page: where Xposure runs is a technical and regulatory decision that comes before any commercial conversation."
          ar="لا أسعار في هذه الصفحة: فمكان تشغيل Xposure قرار تقني وتنظيمي يسبق أي نقاش تجاري."
        />
      </p>
    </main>
  );
}
