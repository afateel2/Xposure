import Link from "next/link";
import type { HTMLAttributes, ReactNode } from "react";

/**
 * Design system card. `title`/`icon`/`actions` render the header row used by
 * the prototypes (title and icon at the start, actions at the end). Use
 * `flush` for tables and lists that should touch the card edge, `lift` or
 * `interactive` for the hover-lift effect, `pad={false}` to drop body padding.
 */
export function Card({
  title, icon, actions, children, className, flush, lift, interactive, pad = true, headless, as: Tag = "div", ...rest
}: {
  title?: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
  flush?: boolean;
  lift?: boolean;
  interactive?: boolean;
  pad?: boolean;
  headless?: boolean;
  as?: "div" | "section" | "article";
} & Omit<HTMLAttributes<HTMLElement>, "title">) {
  const cls = ["xp-card", flush ? "xp-card-flush" : "", lift ? "is-lift" : "", interactive ? "is-interactive" : "", className ?? ""].filter(Boolean).join(" ");
  const hasHead = !headless && (title || icon || actions);
  return (
    <Tag className={cls} {...rest}>
      {hasHead && (
        <div className="xp-card-head">
          {icon}
          {title && <h3>{title}</h3>}
          {actions && <div className="xp-card-actions">{actions}</div>}
        </div>
      )}
      {flush ? children : pad ? <div className="xp-card-body">{children}</div> : children}
    </Tag>
  );
}

export type StatTone = "default" | "critical" | "success" | "warning" | "info";

/**
 * KPI stat card. tone="critical" adds the danger inline-start border and
 * colours the number. `trend` is the small line below (for example "12 this
 * week"); give trendTone to colour it. Pass `href` to make the card a link.
 */
export function StatCard({
  label, value, unit, trend, trendTone, tone = "default", icon, href, className,
}: {
  label: ReactNode;
  value: ReactNode;
  /** Secondary unit shown small after the value, e.g. "/15". */
  unit?: ReactNode;
  trend?: ReactNode;
  trendTone?: "success" | "danger" | "warning";
  tone?: StatTone;
  icon?: ReactNode;
  href?: string;
  className?: string;
}) {
  const cls = ["xp-stat", tone === "critical" ? "is-critical" : tone !== "default" ? `tone-${tone}` : "", className ?? ""].filter(Boolean).join(" ");
  const body = (
    <>
      <div className="xp-stat-head">
        <span>{label}</span>
        {icon}
      </div>
      <div className="xp-stat-num">
        {value}
        {unit != null && <small>{unit}</small>}
      </div>
      {trend != null && <div className={`xp-stat-note${trendTone ? ` tone-${trendTone}` : ""}`}>{trend}</div>}
    </>
  );
  return href ? (
    <Link href={href} className={cls}>{body}</Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}
