import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowLeft } from "lucide-react";

/**
 * Standard page header: optional back link, title (Cairo), subtitle, and an
 * actions slot at the inline-end (put at most ONE primary button there).
 * Every page starts with this.
 */
export function PageHeader({
  title, subtitle, actions, back, className,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  back?: { href: string; label: ReactNode };
  className?: string;
}) {
  return (
    <header className={`page-header${className ? ` ${className}` : ""}`}>
      <div className="page-header-text">
        {back && (
          <Link href={back.href} className="page-back">
            <ArrowLeft size={16} strokeWidth={2} className="xp-icon xp-flip-rtl" aria-hidden="true" />
            {back.label}
          </Link>
        )}
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="page-header-actions">{actions}</div>}
    </header>
  );
}
