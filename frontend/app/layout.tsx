import type { Metadata } from "next";
import { AppShell } from "@/components/AppShell";
import { THEME_INIT_SCRIPT } from "@/lib/theme-init";
import "./globals.css";

export const metadata: Metadata = {
  title: "Xposure",
  description: "Regulatory change monitoring for Saudi industrial and defense organizations: detects regulation changes, diffs versions clause by clause, scores impact, and routes remediation actions.",
  icons: { icon: "/brand/xposure-logo.png" },
};

// Cairo (headings) + Tajawal (body) + Roboto Mono (code), as in the design system.
// A plain stylesheet link (not next/font) so the app still renders with the
// system fallbacks in globals.css when the machine is offline.
const FONTS_HREF =
  "https://fonts.googleapis.com/css2?family=Cairo:wght@600;700&family=Roboto+Mono:wght@400;500&family=Tajawal:wght@400;500;700&display=swap";

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ar" dir="rtl" data-lang="ar" data-theme="dark" suppressHydrationWarning>
      <head>
        {/* Sets data-theme and language on <html> before first paint (no flash). */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href={FONTS_HREF} rel="stylesheet" />
      </head>
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
