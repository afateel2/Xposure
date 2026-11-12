import { useEffect, useState } from "react";

export type Theme = "dark" | "light";

const THEME_STORAGE_KEY = "xposure_theme";

/** Dark is the design system default. */
export function getStoredTheme(fallback: Theme = "dark"): Theme {
  if (typeof window === "undefined") return fallback;
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    return saved === "light" || saved === "dark" ? saved : fallback;
  } catch {
    return fallback;
  }
}

export function setStoredTheme(theme: Theme): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // localStorage unavailable (private mode): best-effort only
  }
}

/** Sets html[data-theme]. The initial value is applied before paint by THEME_INIT_SCRIPT in layout.tsx. */
export function applyThemeToDocument(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
}

/** Reactive current theme (watches html[data-theme]). */
export function useTheme(): Theme {
  const [theme, setTheme] = useState<Theme>("dark");
  useEffect(() => {
    const root = document.documentElement;
    const read = () => setTheme(root.getAttribute("data-theme") === "light" ? "light" : "dark");
    read();
    const observer = new MutationObserver(read);
    observer.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);
  return theme;
}
