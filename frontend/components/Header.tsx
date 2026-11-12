"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Bell, LogOut, Menu, Search, Sun, Moon, User } from "lucide-react";
import { getHealth } from "@/lib/api";
import { displayName, logout, setSessionResult, useSession } from "@/lib/auth";
import { applyLangToDocument, getStoredLang, setStoredLang, t, useLang, type Lang } from "@/lib/lang";
import { useShellState } from "@/lib/shell";
import { applyThemeToDocument, setStoredTheme, useTheme } from "@/lib/theme";
import { getStoredWhoAmI, setStoredWhoAmI } from "@/lib/whoami";
import { Bi } from "./Bi";
import { BrandMotif } from "./ui/BrandMotif";

type HealthState = "checking" | "ok" | "degraded" | "offline";

/**
 * Top bar of the app shell (the sidebar lives in Sidebar.tsx): search, health
 * dot, theme toggle, AR/EN toggle, notification bell and avatar.
 *
 * Feed the bell through lib/shell.ts (setNotificationCount / setNotifications).
 */
export function Header({ navOpen, onToggleNav }: { navOpen: boolean; onToggleNav: () => void }) {
  const router = useRouter();
  const lang = useLang();
  const theme = useTheme();
  const shell = useShellState();
  const session = useSession();
  const [health, setHealth] = useState<HealthState>("checking");
  const [query, setQuery] = useState("");
  const [bellOpen, setBellOpen] = useState(false);
  const [userOpen, setUserOpen] = useState(false);
  const bellRef = useRef<HTMLDivElement>(null);
  const userRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    applyLangToDocument(getStoredLang());
  }, []);

  useEffect(() => {
    // A real signed-in identity (app/auth.py) is a sensible default for the
    // "assigned to me" filter on /changes and /tasks (lib/whoami.ts), but
    // only ever a default: never overwrite something already typed there.
    if (session.user && !getStoredWhoAmI().trim()) {
      setStoredWhoAmI(session.user.name_en);
    }
  }, [session.user]);

  async function onSignOut() {
    await logout().catch(() => undefined);
    setSessionResult({ authenticated: false, user: null });
    setUserOpen(false);
    router.push("/login");
  }

  useEffect(() => {
    getHealth()
      .then((h) => setHealth(h.ready ? "ok" : h.status === "offline" ? "offline" : "degraded"))
      .catch(() => setHealth("offline"));
  }, []);

  useEffect(() => {
    if (!bellOpen) return;
    const onDown = (e: MouseEvent) => {
      if (bellRef.current && !bellRef.current.contains(e.target as Node)) setBellOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setBellOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [bellOpen]);

  useEffect(() => {
    if (!userOpen) return;
    const onDown = (e: MouseEvent) => {
      if (userRef.current && !userRef.current.contains(e.target as Node)) setUserOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setUserOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [userOpen]);

  function selectLang(next: Lang) {
    setStoredLang(next);
    applyLangToDocument(next);
  }

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    applyThemeToDocument(next);
    setStoredTheme(next);
  }

  function submitSearch(e: FormEvent) {
    e.preventDefault();
    const q = query.trim();
    router.push(q ? `/changes?q=${encodeURIComponent(q)}` : "/changes");
  }

  const bellCount = shell.notificationCount ?? shell.notifications.length;
  const healthText =
    health === "checking"
      ? { en: "Checking...", ar: "جارٍ الفحص..." }
      : health === "ok"
        ? { en: "All systems reachable", ar: "جميع الأنظمة متصلة" }
        : health === "degraded"
          ? { en: "Degraded", ar: "أداء منخفض" }
          : { en: "Backend unreachable", ar: "الخادم غير متصل" };

  return (
    <div className="topbar">
      <button
        type="button"
        className="icon-btn menu-btn"
        aria-label={t(lang, "Open navigation", "فتح القائمة")}
        aria-expanded={navOpen}
        aria-controls="app-sidebar"
        onClick={onToggleNav}
      >
        <Menu size={18} strokeWidth={2} aria-hidden="true" />
      </button>

      <form className="topbar-search" role="search" onSubmit={submitSearch}>
        <Search size={16} strokeWidth={2} className="xp-icon" aria-hidden="true" />
        <input
          type="search"
          name="q"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t(lang, "Search changes and clauses...", "ابحث في التغييرات والبنود...")}
          aria-label={t(lang, "Search changes and clauses", "ابحث في التغييرات والبنود")}
        />
      </form>

      <div className="topbar-spacer" />

      <div className="topbar-actions">
        <span className={`status-dot ${health === "ok" ? "ok" : health === "offline" ? "offline" : ""}`} role="status">
          <i />
          <span><Bi en={healthText.en} ar={healthText.ar} /></span>
        </span>

        <button
          type="button"
          className="icon-btn"
          onClick={toggleTheme}
          aria-label={theme === "dark" ? t(lang, "Switch to light theme", "التبديل إلى الوضع الفاتح") : t(lang, "Switch to dark theme", "التبديل إلى الوضع الداكن")}
          title={theme === "dark" ? t(lang, "Light theme", "الوضع الفاتح") : t(lang, "Dark theme", "الوضع الداكن")}
        >
          {theme === "dark" ? <Sun size={18} strokeWidth={2} aria-hidden="true" /> : <Moon size={18} strokeWidth={2} aria-hidden="true" />}
        </button>

        <div className="lang-toggle" role="group" aria-label={t(lang, "Language", "اللغة")}>
          <button type="button" aria-pressed={lang === "ar"} onClick={() => selectLang("ar")}>AR</button>
          <button type="button" aria-pressed={lang === "en"} onClick={() => selectLang("en")}>EN</button>
        </div>

        <div className="popover-anchor" ref={bellRef}>
          <button
            type="button"
            className="icon-btn"
            aria-label={t(lang, "Notifications", "الإشعارات")}
            aria-expanded={bellOpen}
            aria-haspopup="true"
            onClick={() => setBellOpen((v) => !v)}
          >
            <Bell size={18} strokeWidth={2} aria-hidden="true" />
            {bellCount > 0 && <span className="bell-count">{bellCount > 99 ? "99+" : bellCount}</span>}
          </button>
          {bellOpen && (
            <div className="xp-popover" role="dialog" aria-label={t(lang, "Notifications", "الإشعارات")}>
              <div className="xp-popover-head"><Bi en="Notifications" ar="الإشعارات" /></div>
              {shell.notifications.length > 0 ? (
                <ul className="xp-popover-list">
                  {shell.notifications.map((n) => (
                    <li key={n.id}>
                      {n.href ? (
                        <Link href={n.href} onClick={() => setBellOpen(false)}><Bi en={n.en} ar={n.ar} /></Link>
                      ) : (
                        <span className="xp-popover-item"><Bi en={n.en} ar={n.ar} /></span>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <BrandMotif
                  compact
                  title={<Bi en="Nothing needs your attention" ar="لا توجد إشعارات جديدة" />}
                  hint={bellCount > 0 ? <Bi en={`${bellCount} items are waiting for review.`} ar={`${bellCount} عناصر بانتظار المراجعة.`} /> : undefined}
                />
              )}
            </div>
          )}
        </div>

        {session.user ? (
          <div className="popover-anchor" ref={userRef}>
            <button
              type="button"
              className="avatar-btn"
              aria-label={t(lang, "Account", "الحساب")}
              aria-expanded={userOpen}
              aria-haspopup="true"
              onClick={() => setUserOpen((v) => !v)}
            >
              <span className="avatar">{displayName(session.user, lang).trim().charAt(0).toUpperCase()}</span>
            </button>
            {userOpen && (
              <div className="xp-popover" role="dialog" aria-label={t(lang, "Account", "الحساب")}>
                <div className="userpop-head">
                  <span className="userpop-name">{displayName(session.user, lang)}</span>
                  <span className="userpop-role">
                    {lang === "ar" ? session.user.job_title_ar ?? session.user.role : session.user.job_title_en ?? session.user.role}
                  </span>
                </div>
                <button type="button" className="xp-popover-item" onClick={onSignOut}>
                  <LogOut size={14} strokeWidth={2} aria-hidden="true" style={{ marginInlineEnd: 6, verticalAlign: "-2px" }} />
                  <Bi en="Sign out" ar="تسجيل الخروج" />
                </button>
              </div>
            )}
          </div>
        ) : !session.loading ? (
          <Link href="/login" className="avatar-btn" title={t(lang, "Sign in to approve, delegate, or run a scan", "سجّل الدخول للاعتماد أو الإسناد أو تشغيل فحص")}>
            <span className="avatar"><User size={16} strokeWidth={2} aria-hidden="true" /></span>
          </Link>
        ) : (
          <span className="avatar" aria-hidden="true" />
        )}
      </div>
    </div>
  );
}
