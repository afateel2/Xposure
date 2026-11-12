import { useEffect, useState } from "react";

export type Lang = "ar" | "en";

const LANG_STORAGE_KEY = "xposure_lang";

/**
 * Shared language preference across pages. Read only inside a mount
 * useEffect, never as a lazy useState initializer: SSR always renders
 * `fallback`, so reading localStorage synchronously during render would
 * mismatch client hydration. Pattern carried over from ComplyX's lib/lang.ts.
 */
export function getStoredLang(fallback: Lang = "ar"): Lang {
  if (typeof window === "undefined") return fallback;
  try {
    const saved = localStorage.getItem(LANG_STORAGE_KEY);
    return saved === "en" || saved === "ar" ? saved : fallback;
  } catch {
    return fallback;
  }
}

export function setStoredLang(lang: Lang): void {
  try {
    localStorage.setItem(LANG_STORAGE_KEY, lang);
  } catch {
    // localStorage unavailable (private mode) or quota exceeded — best-effort only
  }
}

/**
 * Applies a language directly to <html>'s dir/lang/data-lang attributes.
 * Direct DOM mutation, not React state: globals.css's [data-only] rules
 * key off document.documentElement, and every page's bilingual text is
 * rendered via <Bi> (components/Bi.tsx) with both languages always in the
 * DOM, so no component needs to re-render when this changes.
 */
export function applyLangToDocument(lang: Lang): void {
  const root = document.documentElement;
  root.setAttribute("data-lang", lang);
  root.setAttribute("lang", lang);
  root.setAttribute("dir", lang === "ar" ? "rtl" : "ltr");
}

/**
 * Reactive current-language read, for the few cases <Bi> (components/Bi.tsx)
 * can't cover: a real HTML attribute value (placeholder, aria-label) rather
 * than DOM content, which CSS's [data-only] toggle can't switch between two
 * strings for. Watches html[data-lang] via MutationObserver rather than
 * polling — <Header>'s toggle flips that attribute directly (not React
 * state), so this is the only way a plain-string value can follow it live.
 */
export function useLang(): Lang {
  const [lang, setLang] = useState<Lang>("ar");
  useEffect(() => {
    const root = document.documentElement;
    const read = () => setLang(root.getAttribute("data-lang") === "en" ? "en" : "ar");
    read();
    const observer = new MutationObserver(read);
    observer.observe(root, { attributes: true, attributeFilter: ["data-lang"] });
    return () => observer.disconnect();
  }, []);
  return lang;
}

/** Picks the plain string for the current language — for the same
 * attribute-value cases useLang() exists for, not for DOM content
 * (use <Bi> for that). */
export function t(lang: Lang, en: string, ar: string): string {
  return lang === "ar" ? ar : en;
}
