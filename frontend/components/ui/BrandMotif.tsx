import type { ReactNode } from "react";

const SHARD_ANGLES = [0, 60, 120, 180, 240, 300];

/**
 * The "lens and shatter" motif, taken literally from the logo. Use ONLY for
 * loading (variant="spinner") and empty states (variant="empty"). Always
 * ink-muted, never brand coloured.
 *
 *   <BrandMotif variant="spinner" title={<Bi en="Loading..." ar="جارٍ التحميل..." />} />
 *   <BrandMotif variant="empty" title={<Bi .../>} hint={<Bi .../>} />
 */
export function BrandMotif({
  variant = "empty", title, hint, compact, className, children,
}: {
  variant?: "spinner" | "empty";
  title?: ReactNode;
  hint?: ReactNode;
  compact?: boolean;
  className?: string;
  children?: ReactNode;
}) {
  const cls = `xp-motif${compact ? " is-compact" : ""}${className ? ` ${className}` : ""}`;
  return (
    <div className={cls} role={variant === "spinner" ? "status" : undefined} aria-live={variant === "spinner" ? "polite" : undefined}>
      {variant === "spinner" ? (
        <svg width="56" height="56" viewBox="0 0 56 56" className="xp-motif-spin" aria-hidden="true">
          <g fill="currentColor">
            {SHARD_ANGLES.map((a) => (
              <polygon key={a} points="28,28 46,21 40,34" transform={`rotate(${a} 28 28)`} />
            ))}
          </g>
        </svg>
      ) : (
        <svg width="72" height="72" viewBox="0 0 72 72" aria-hidden="true">
          <g fill="currentColor">
            {SHARD_ANGLES.map((a) => (
              <polygon key={a} points="36,36 58,27 51,44" transform={`rotate(${a} 36 36)`} />
            ))}
          </g>
          <g fill="currentColor" opacity="0.6">
            <circle cx="6" cy="30" r="2.4" />
            <circle cx="12" cy="22" r="1.8" />
            <circle cx="4" cy="42" r="1.6" />
            <circle cx="14" cy="50" r="2.2" />
          </g>
        </svg>
      )}
      {title && <div className="xp-motif-title">{title}</div>}
      {hint && <div className="xp-motif-hint">{hint}</div>}
      {children}
    </div>
  );
}
