"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { Header } from "./Header";
import { ShellFeed } from "./ShellFeed";
import { Sidebar } from "./Sidebar";
import { ToastProvider } from "./ui/Toast";

/**
 * App shell: sidebar at the inline-start (right in Arabic), top bar above the
 * content column, toast provider around everything. Below 1180px the sidebar
 * collapses to an icon rail; below 760px it becomes an off-canvas drawer.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    setNavOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!navOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setNavOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [navOpen]);

  // The public landing page (/welcome) is not part of the app: no sidebar, no top bar.
  if (pathname === "/welcome" || pathname?.startsWith("/welcome/")) {
    return <ToastProvider>{children}</ToastProvider>;
  }

  return (
    <ToastProvider>
      <ShellFeed />
      <div className="app-shell">
        <Sidebar open={navOpen} onNavigate={() => setNavOpen(false)} />
        <div className={`sidebar-scrim${navOpen ? " is-open" : ""}`} onClick={() => setNavOpen(false)} aria-hidden="true" />
        <div className="app-body">
          <Header navOpen={navOpen} onToggleNav={() => setNavOpen((v) => !v)} />
          <div className="app-content" id="content">{children}</div>
        </div>
      </div>
    </ToastProvider>
  );
}
