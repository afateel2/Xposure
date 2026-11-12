import type { ReactNode } from "react";

/**
 * Confidence track with a threshold marker (design system "confidence bar").
 * value and threshold are 0..1 (or 0..100, auto-detected). Colour: at or
 * above threshold = success, within 15 points below = warning, else danger.
 * Both the fill and the marker start from the inline-start edge, so it
 * mirrors in RTL.
 */
export function ConfidenceBar({
  value, threshold = 0.7, label, note, showValue = true, className,
}: {
  value: number;
  threshold?: number;
  label?: ReactNode;
  note?: ReactNode;
  showValue?: boolean;
  className?: string;
}) {
  const norm = (n: number) => Math.min(1, Math.max(0, n > 1 ? n / 100 : n));
  const v = norm(value);
  const th = norm(threshold);
  const tone = v >= th ? "success" : v >= th - 0.15 ? "warning" : "danger";
  const pct = Math.round(v * 100);
  return (
    <div className={`tone-${tone}${className ? ` ${className}` : ""}`}>
      {(label || showValue) && (
        <div className="xp-conf-head">
          <span className="lbl">{label}</span>
          {showValue && <span className="val tabular">{pct}%</span>}
        </div>
      )}
      <div className="xp-conf-track" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
        <div className="xp-conf-fill" style={{ width: `${pct}%` }} />
        <div className="xp-conf-threshold" style={{ insetInlineStart: `${Math.round(th * 100)}%` }} title={`${Math.round(th * 100)}%`} />
      </div>
      {note && <div className="xp-conf-note">{note}</div>}
    </div>
  );
}
