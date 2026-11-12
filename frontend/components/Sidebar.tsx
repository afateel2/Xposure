"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { LucideIcon } from "lucide-react";
import { BookOpen, Building2, FlaskConical, FileDiff, Globe, History, LayoutDashboard, ListChecks, Bot, Plug, Server, Settings, TrendingUp } from "lucide-react";
import { t, useLang } from "@/lib/lang";
import { useShellState, type NavBadgeKey } from "@/lib/shell";
import { Bi } from "./Bi";
import { Logo } from "./Logo";

interface NavItem {
  href: string;
  en: string;
  ar: string;
  icon: LucideIcon;
  badge?: NavBadgeKey;
  badgeTone?: "danger" | "warning";
}

interface NavSection {
  en: string;
  ar: string;
  items: NavItem[];
}

/** Sections and items follow the team prototype (Monitoring, Actions, Setup). */
export const NAV_SECTIONS: NavSection[] = [
  {
    en: "Monitoring", ar: "المراقبة",
    items: [
      { href: "/", en: "Dashboard", ar: "لوحة التحكم", icon: LayoutDashboard },
      { href: "/agent", en: "Run agent", ar: "تشغيل الوكيل", icon: Bot },
      { href: "/changes", en: "Changes", ar: "التغييرات", icon: FileDiff, badge: "changes", badgeTone: "danger" },
    ],
  },
  {
    en: "Actions", ar: "الإجراءات",
    items: [
      { href: "/tasks", en: "Tasks", ar: "المهام", icon: ListChecks, badge: "tasks", badgeTone: "warning" },
      { href: "/audit", en: "Audit log", ar: "سجل التدقيق", icon: History },
    ],
  },
  {
    en: "Setup", ar: "الإعداد",
    items: [
      { href: "/company", en: "Facility profile", ar: "ملف المنشأة", icon: Building2 },
      { href: "/sources", en: "Regulatory sources", ar: "المصادر التنظيمية", icon: Globe },
      { href: "/trends", en: "Trends", ar: "الاتجاهات", icon: TrendingUp },
      { href: "/integrations", en: "Integrations", ar: "التكاملات", icon: Plug },
      { href: "/settings", en: "Settings", ar: "الإعدادات", icon: Settings },
    ],
  },
  {
    en: "Help", ar: "المساعدة",
    items: [
      { href: "/help", en: "User guide", ar: "دليل الاستخدام", icon: BookOpen },
      { href: "/deployment", en: "Deployment options", ar: "خيارات النشر", icon: Server },
    ],
  },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function Sidebar({ open, onNavigate }: { open: boolean; onNavigate: () => void }) {
  const pathname = usePathname() ?? "/";
  const { badges } = useShellState();
  const lang = useLang();

  return (
    <aside className={`sidebar${open ? " is-open" : ""}`} id="app-sidebar" aria-label="Primary">
      <Link href="/" className="sidebar-brand" onClick={onNavigate} aria-label="Xposure">
        <Logo size={48} inverted className="brand-logo" />
        <span className="brand-tagline"><Bi en="Regulatory compliance agent" ar="وكيل الامتثال التنظيمي" /></span>
      </Link>

      <nav className="sidebar-nav">
        {NAV_SECTIONS.map((section) => (
          <div key={section.en} style={{ display: "contents" }}>
            <div className="sidebar-section"><Bi en={section.en} ar={section.ar} /></div>
            {section.items.map((item) => {
              const Glyph = item.icon;
              const count = item.badge ? badges[item.badge] : undefined;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className="sidebar-item"
                  aria-current={isActive(pathname, item.href) ? "page" : undefined}
                  onClick={onNavigate}
                >
                  <Glyph size={18} strokeWidth={2} className="xp-icon" aria-hidden="true" />
                  <span className="sidebar-item-label"><Bi en={item.en} ar={item.ar} /></span>
                  {count ? (
                    <>
                      <span className={`nav-badge${item.badgeTone === "warning" ? " warning" : ""}`}>{count}</span>
                      <span className={`rail-dot${item.badgeTone === "warning" ? " warning" : ""}`} aria-hidden="true" />
                    </>
                  ) : null}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="sidebar-foot">
        <div className="demo-chip" title={t(lang, "Illustrative data for a fictional company, not a real customer.", "بيانات توضيحية لشركة افتراضية وليست عميلاً حقيقياً.")}>
          <FlaskConical size={16} strokeWidth={2} className="xp-icon" aria-hidden="true" />
          <div>
            <b><Bi en="Demo company data" ar="بيانات شركة توضيحية" /></b>
            <span><Bi en="Eastern Industrial Company (fictional)" ar="الشركة الصناعية الشرقية (افتراضية)" /></span>
          </div>
        </div>
      </div>
    </aside>
  );
}
