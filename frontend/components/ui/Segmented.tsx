"use client";

import type { ReactNode } from "react";

/**
 * Segmented filter control (single choice). Neutral styling, never brand blue.
 *
 *   <Segmented value={band} onChange={setBand} ariaLabel="Priority"
 *     options={[{ value: "all", label: <Bi en="All" ar="الكل" /> }, ...]} />
 */
export function Segmented<T extends string>({
  value, onChange, options, ariaLabel, className,
}: {
  value: T;
  onChange: (next: T) => void;
  options: { value: T; label: ReactNode }[];
  ariaLabel?: string;
  className?: string;
}) {
  return (
    <div className={`xp-seg${className ? ` ${className}` : ""}`} role="group" aria-label={ariaLabel}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
