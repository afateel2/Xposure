"use client";

import Link from "next/link";
import { useEffect } from "react";
import { Moon, Sun } from "lucide-react";
import { Bi } from "@/components/Bi";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui";
import { applyLangToDocument, getStoredLang, setStoredLang, t, useLang, type Lang } from "@/lib/lang";
import { applyThemeToDocument, setStoredTheme, useTheme } from "@/lib/theme";

const NAV_LINKS: { href: string; en: string; ar: string }[] = [
  { href: "#problem", en: "Problem", ar: "المشكلة" },
  { href: "#how", en: "How it works", ar: "كيف يعمل" },
  { href: "#roles", en: "Who it is for", ar: "لمن هو" },
  { href: "#trust", en: "Trust", ar: "الثقة" },
  { href: "#about", en: "About", ar: "عن المشروع" },
  { href: "#demo", en: "Request a demo", ar: "اطلب عرضًا" },
];

/**
 * Sticky top bar of the public landing page: brand, in-page anchors (hidden
 * below 900px), language and theme toggles (same approach as components/Header
 * in the app shell) and the primary call to action.
 */
export function SiteNav() {
  const lang = useLang();
  const theme = useTheme();

  useEffect(() => {
    applyLangToDocument(getStoredLang());
  }, []);

  function selectLang(next: Lang) {
    setStoredLang(next);
    applyLangToDocument(next);
  }

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    applyThemeToDocument(next);
    setStoredTheme(next);
  }

  return (
    <header className="site-nav">
      <div className="site-wrap site-nav-inner">
        <Link href="/welcome" className="site-brand">
          <Logo size={30} />
        </Link>

        <nav className="site-nav-links" aria-label={t(lang, "Page sections", "أقسام الصفحة")}>
          <ul className="site-nav-list">
            {NAV_LINKS.map((link) => (
              <li key={link.href}>
                <a href={link.href}>
                  <Bi en={link.en} ar={link.ar} />
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <div className="site-nav-actions">
          <div className="site-lang" role="group" aria-label={t(lang, "Language", "اللغة")}>
            <button type="button" aria-pressed={lang === "ar"} onClick={() => selectLang("ar")}>
              AR
            </button>
            <button type="button" aria-pressed={lang === "en"} onClick={() => selectLang("en")}>
              EN
            </button>
          </div>

          <button
            type="button"
            className="site-icon-btn"
            onClick={toggleTheme}
            aria-label={
              theme === "dark"
                ? t(lang, "Switch to light theme", "التبديل إلى الوضع الفاتح")
                : t(lang, "Switch to dark theme", "التبديل إلى الوضع الداكن")
            }
            title={theme === "dark" ? t(lang, "Light theme", "الوضع الفاتح") : t(lang, "Dark theme", "الوضع الداكن")}
          >
            {theme === "dark" ? <Sun size={18} strokeWidth={2} aria-hidden="true" /> : <Moon size={18} strokeWidth={2} aria-hidden="true" />}
          </button>

          <Button href="/" variant="primary" size="sm">
            <span className="site-cta-long">
              <Bi en="Open the live demo" ar="افتح العرض المباشر" />
            </span>
            <span className="site-cta-short">
              <Bi en="Live demo" ar="العرض المباشر" />
            </span>
          </Button>
        </div>
      </div>
    </header>
  );
}
