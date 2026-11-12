"use client";

import { useState } from "react";
import { Bi } from "@/components/Bi";
import {
  Add, Badge, BrandMotif, Button, Card, Checkbox, ConfidenceBar, DataTable, Del, DiffColumns, Field, Icon, Input,
  Modal, PageHeader, PriorityPill, Segmented, Select, StatCard, Textarea, useToast,
  Bell, Check, ClipboardCheck, FileText, LayoutDashboard, Play, Search, Settings, TrendingUp, TriangleAlert, Undo2,
} from "@/components/ui";
import { setNavBadge, setNotificationCount } from "@/lib/shell";

/**
 * Visual reference for every design system primitive. Flip the theme and the
 * language in the top bar to check both. Not linked from the sidebar.
 */
export default function UiKitPage() {
  const toast = useToast();
  const [modalOpen, setModalOpen] = useState(false);
  const [seg, setSeg] = useState<"all" | "critical" | "open">("all");

  return (
    <main>
      <PageHeader
        title={<Bi en="UI kit" ar="مكتبة المكونات" />}
        subtitle={<Bi en="Every primitive of the Xposure design system, live in both themes and both languages." ar="كل مكونات نظام تصميم Xposure، مباشرة في الوضعين واللغتين." />}
        actions={<Button variant="primary" icon={<Icon icon={Play} size={16} />}><Bi en="Primary action" ar="الإجراء الرئيسي" /></Button>}
      />

      <h2 className="xp-section-title"><Bi en="Buttons" ar="الأزرار" /></h2>
      <div className="row">
        <Button variant="primary"><Bi en="Approve" ar="اعتماد" /></Button>
        <Button variant="secondary"><Bi en="Request more analysis" ar="طلب تحليل إضافي" /></Button>
        <Button variant="success" icon={<Icon icon={Check} size={16} />}><Bi en="Save" ar="حفظ" /></Button>
        <Button variant="danger"><Bi en="Reject" ar="رفض" /></Button>
        <Button variant="ghost"><Bi en="Cancel" ar="إلغاء" /></Button>
        <Button variant="link"><Bi en="Open details" ar="فتح التفاصيل" /></Button>
        <Button variant="primary" disabled><Bi en="Disabled" ar="معطّل" /></Button>
        <Button variant="secondary" loading><Bi en="Working" ar="جارٍ التنفيذ" /></Button>
        <Button variant="secondary" size="sm"><Bi en="Small" ar="صغير" /></Button>
        <Button variant="primary" size="lg"><Bi en="Large" ar="كبير" /></Button>
        <Button variant="secondary" iconOnly aria-label="Settings"><Icon icon={Settings} size={16} /></Button>
      </div>
      <p className="xp-muted" style={{ marginBlockStart: 8, fontSize: 13 }}>
        <Bi en="One brand (primary) button per screen area." ar="زر brand واحد فقط للإجراء الرئيسي في كل منطقة من الشاشة." />
      </p>

      <h2 className="xp-section-title"><Bi en="Badges and priority pills" ar="الشارات وشارات الأولوية" /></h2>
      <div className="row">
        <Badge variant="new"><Bi en="New" ar="جديد" /></Badge>
        <Badge variant="pending"><Bi en="Pending" ar="معلق" /></Badge>
        <Badge variant="approved"><Bi en="Approved" ar="معتمد" /></Badge>
        <Badge variant="rejected"><Bi en="Rejected" ar="مرفوض" /></Badge>
        <Badge variant="neutral"><Bi en="Dismissed" ar="مُتجاهَل" /></Badge>
      </div>
      <div className="row" style={{ marginBlockStart: 12 }}>
        <PriorityPill priority="critical" />
        <PriorityPill priority="strategic" />
        <PriorityPill priority="quick" />
        <PriorityPill priority="followup" />
        <PriorityPill band="high" />
      </div>

      <h2 className="xp-section-title"><Bi en="Cards and KPI stat cards" ar="البطاقات ومؤشرات الأداء" /></h2>
      <div className="xp-grid cols-3" style={{ marginBlockEnd: 16 }}>
        <Card lift headless>
          <div className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap", marginBlockEnd: 8 }}>
            <h3 style={{ fontSize: 16 }}><Bi en="Stricter encryption requirements" ar="تشديد متطلبات التشفير" /></h3>
            <PriorityPill priority="critical" />
          </div>
          <p className="xp-muted" style={{ fontSize: 13, marginBlockEnd: 12 }}>
            <Bi en="Cybersecurity, ECC-2:2024: two products and two processes affected" ar="الأمن السيبراني، ECC-2:2024: منتجان وعمليتان متأثرتان" />
          </p>
          <div className="row" style={{ justifyContent: "space-between", paddingBlockStart: 10, borderBlockStart: "1px solid var(--border)", fontSize: 13 }}>
            <span className="xp-muted"><Bi en="3 hours ago" ar="قبل 3 ساعات" /></span>
            <Button variant="link" size="sm"><Bi en="Open details" ar="فتح التفاصيل" /></Button>
          </div>
        </Card>
        <Card title={<Bi en="Card with header" ar="بطاقة برأس" />} icon={<Icon icon={FileText} size={18} />} actions={<Button variant="ghost" size="sm"><Bi en="Action" ar="إجراء" /></Button>}>
          <p className="xp-muted" style={{ fontSize: 13.5 }}>
            <Bi en="Title and icon at the start, actions at the end, body below." ar="العنوان والأيقونة في البداية، والإجراءات في النهاية، والمحتوى أسفلهما." />
          </p>
        </Card>
      </div>
      <div className="xp-grid cols-4">
        <StatCard label={<Bi en="Total changes" ar="إجمالي التغييرات" />} value="47" trend={<Bi en="12 this week" ar="12 هذا الأسبوع" />} trendTone="success" icon={<Icon icon={TrendingUp} size={16} />} />
        <StatCard tone="critical" label={<Bi en="Critical issues" ar="قضايا حرجة" />} value="3" trend={<Bi en="Need approval now" ar="تتطلب اعتماداً فورياً" />} icon={<Icon icon={TriangleAlert} size={16} />} />
        <StatCard label={<Bi en="Tasks done" ar="المهام المنجزة" />} value="12" unit="/15" trend={<Bi en="80% completion" ar="80% نسبة الإنجاز" />} icon={<Icon icon={ClipboardCheck} size={16} />} />
        <StatCard tone="success" label={<Bi en="Compliance score" ar="درجة الامتثال" />} value="85%" trend={<Bi en="Previous quarter: 78%" ar="الربع السابق: 78%" />} icon={<Icon icon={LayoutDashboard} size={16} />} />
      </div>

      <h2 className="xp-section-title"><Bi en="Diff columns and confidence bar" ar="مقارنة النصوص وشريط الثقة" /></h2>
      <DiffColumns
        beforeLabel={<Bi en="Previous version, ECC-1:2018" ar="الإصدار السابق · ECC-1:2018" />}
        afterLabel={<Bi en="New version, ECC-2:2024" ar="الإصدار الجديد · ECC-2:2024" />}
        before={<Bi en={<>Appropriate cryptographic mechanisms must be applied to <Del>sensitive data</Del>.</>} ar={<>يجب تطبيق آليات تشفير <Del>مناسبة</Del> لحماية البيانات.</>} />}
        after={<Bi en={<>Approved cryptographic mechanisms <Add>(AES-256 or stronger)</Add> must be applied to sensitive data.</>} ar={<>يجب تطبيق آليات تشفير <Add>معتمدة (AES-256 أو أقوى)</Add> لحماية البيانات.</>} />}
      />
      <div className="xp-grid cols-2" style={{ marginBlockStart: 16, maxWidth: 900 }}>
        <ConfidenceBar value={0.95} threshold={0.7} label={<Bi en="Confidence" ar="درجة الثقة" />} />
        <ConfidenceBar value={0.58} threshold={0.7} label={<Bi en="Confidence" ar="درجة الثقة" />} note={<Bi en="Below threshold: routed to manual review" ar="أقل من الحد: حُوّل للمراجعة اليدوية" />} />
      </div>

      <h2 className="xp-section-title"><Bi en="Table" ar="الجدول" /></h2>
      <DataTable>
        <thead>
          <tr>
            <th><Bi en="Change" ar="التغيير" /></th>
            <th><Bi en="Regulator" ar="الجهة" /></th>
            <th><Bi en="Priority" ar="الأولوية" /></th>
            <th><Bi en="Status" ar="الحالة" /></th>
            <th><Bi en="Date" ar="التاريخ" /></th>
          </tr>
        </thead>
        <tbody>
          <tr className="is-clickable">
            <td><Bi en="Stricter encryption requirements" ar="تشديد متطلبات التشفير" /></td>
            <td>NCA</td>
            <td><PriorityPill priority="critical" /></td>
            <td><Badge variant="new"><Bi en="New" ar="جديد" /></Badge></td>
            <td className="mono">2026-09-16</td>
          </tr>
          <tr className="is-clickable">
            <td><Bi en="Updated quality policies" ar="تحديث سياسات الجودة" /></td>
            <td>SASO</td>
            <td><PriorityPill priority="strategic" /></td>
            <td><Badge variant="pending"><Bi en="Pending" ar="معلق" /></Badge></td>
            <td className="mono">2026-09-15</td>
          </tr>
          <tr className="is-clickable">
            <td><Bi en="Clarified annual scan scope" ar="توضيح نطاق الفحص السنوي" /></td>
            <td>NCA</td>
            <td><PriorityPill priority="followup" /></td>
            <td><Badge variant="approved"><Bi en="Approved" ar="معتمد" /></Badge></td>
            <td className="mono">2026-09-10</td>
          </tr>
        </tbody>
      </DataTable>

      <h2 className="xp-section-title"><Bi en="Forms" ar="النماذج" /></h2>
      <div className="xp-grid cols-2" style={{ maxWidth: 760 }}>
        <Field label={<Bi en="Search changes" ar="البحث في التغييرات" />} htmlFor="kit-search">
          <Input id="kit-search" placeholder="..." />
        </Field>
        <Field label={<Bi en="Rejection reason" ar="سبب الرفض" />} htmlFor="kit-reason" error={<Bi en="A change cannot be rejected without a reason." ar="لا يمكن رفض تغيير دون ذكر السبب." />}>
          <Input id="kit-reason" invalid placeholder="..." />
        </Field>
        <Field label={<Bi en="Regulator" ar="الجهة التنظيمية" />} htmlFor="kit-reg">
          <Select id="kit-reg"><option>NCA</option><option>SASO</option></Select>
        </Field>
        <Field label={<Bi en="Note" ar="ملاحظة" />} htmlFor="kit-note" hint={<Bi en="Optional" ar="اختياري" />}>
          <Textarea id="kit-note" rows={2} />
        </Field>
        <Checkbox defaultChecked><Bi en="Include approved changes in the export" ar="تضمين التغييرات المعتمدة في التصدير" /></Checkbox>
        <Segmented
          value={seg}
          onChange={setSeg}
          ariaLabel="Filter"
          options={[
            { value: "all", label: <Bi en="All" ar="الكل" /> },
            { value: "critical", label: <Bi en="Critical" ar="حرج" /> },
            { value: "open", label: <Bi en="Open" ar="مفتوح" /> },
          ]}
        />
      </div>

      <h2 className="xp-section-title"><Bi en="Dialog and toasts" ar="الحوارات والتنبيهات" /></h2>
      <div className="row">
        <Button variant="secondary" onClick={() => setModalOpen(true)}><Bi en="Open dialog" ar="فتح حوار" /></Button>
        <Button variant="secondary" onClick={() => toast.success(<Bi en="Change approved and task created in Odoo." ar="تم اعتماد التغيير وإنشاء المهمة في Odoo." />)}><Bi en="Success toast" ar="تنبيه نجاح" /></Button>
        <Button variant="secondary" onClick={() => toast.error(<Bi en="Could not reach Odoo. Try again." ar="تعذّر الاتصال بنظام Odoo. أعد المحاولة." />)}><Bi en="Error toast" ar="تنبيه خطأ" /></Button>
        <Button variant="secondary" onClick={() => toast.info(<Bi en="The scan is running in the background." ar="الفحص يعمل في الخلفية." />)}><Bi en="Info toast" ar="تنبيه معلومة" /></Button>
      </div>
      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={<Bi en="Confirm rejection" ar="تأكيد الرفض" />}
        footer={
          <>
            <Button variant="secondary" onClick={() => setModalOpen(false)}><Bi en="Cancel" ar="إلغاء" /></Button>
            <Button variant="danger" onClick={() => setModalOpen(false)}><Bi en="Confirm rejection" ar="تأكيد الرفض" /></Button>
          </>
        }
      >
        <Bi en="This decision is recorded in the audit log. Continue?" ar="سيُسجَّل هذا القرار في سجل التدقيق. هل تريد المتابعة؟" />
      </Modal>

      <h2 className="xp-section-title"><Bi en="Brand motif (loading and empty states only)" ar="نمط العدسة والتشظي (للتحميل والحالات الفارغة فقط)" /></h2>
      <div className="xp-grid cols-2">
        <Card><BrandMotif variant="spinner" title={<Bi en="Loading" ar="تحميل" />} /></Card>
        <Card><BrandMotif variant="empty" title={<Bi en="No changes detected yet" ar="لا توجد تغييرات مكتشفة بعد" />} hint={<Bi en="Run a scan to compare the latest regulation versions." ar="شغّل فحصاً لمقارنة أحدث إصدارات الأنظمة." />} /></Card>
      </div>

      <h2 className="xp-section-title"><Bi en="Icons (Lucide, stroke 2)" ar="الأيقونات (Lucide، سماكة 2)" /></h2>
      <div className="row" style={{ gap: 20 }}>
        {[LayoutDashboard, FileText, ClipboardCheck, Settings, Search, Bell, Undo2, TriangleAlert].map((G, i) => (
          <Icon key={i} icon={G} size={22} />
        ))}
      </div>

      <h2 className="xp-section-title"><Bi en="Shell slots (sidebar badges and bell)" ar="خانات الهيكل (شارات القائمة والجرس)" /></h2>
      <div className="row">
        <Button variant="secondary" size="sm" onClick={() => { setNavBadge("changes", 19); setNavBadge("tasks", 3); setNotificationCount(4); }}><Bi en="Show demo badges" ar="إظهار شارات تجريبية" /></Button>
        <Button variant="secondary" size="sm" onClick={() => { setNavBadge("changes", null); setNavBadge("tasks", null); setNotificationCount(null); }}><Bi en="Clear badges" ar="إخفاء الشارات" /></Button>
        <span className="xp-muted" style={{ fontSize: 13 }}>
          <Bi
            en="setNavBadge, setNotificationCount and setNotifications live in lib/shell.ts."
            ar={<>الدوال <bdi>setNavBadge</bdi> و<bdi>setNotificationCount</bdi> و<bdi>setNotifications</bdi> موجودة في <bdi>lib/shell.ts</bdi>.</>}
          />
        </span>
      </div>
    </main>
  );
}
