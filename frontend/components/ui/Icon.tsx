import type { LucideIcon, LucideProps } from "lucide-react";

export type IconProps = Omit<LucideProps, "ref"> & {
  /** A lucide icon component, e.g. `icon={Search}`. */
  icon: LucideIcon;
  /** Mirror the glyph in RTL (arrows, chevrons, "next/back" glyphs). */
  flipRtl?: boolean;
  /** Accessible name. Omit for decorative icons (they get aria-hidden). */
  label?: string;
};

/**
 * Design system icon wrapper: Lucide, stroke width 2, decorative by default,
 * optional RTL mirroring for directional glyphs.
 */
export function Icon({ icon: Cmp, size = 18, strokeWidth = 2, flipRtl, label, className, ...rest }: IconProps) {
  const cls = ["xp-icon", flipRtl ? "xp-flip-rtl" : "", className ?? ""].filter(Boolean).join(" ");
  return (
    <Cmp
      size={size}
      strokeWidth={strokeWidth}
      className={cls}
      aria-hidden={label ? undefined : true}
      aria-label={label}
      role={label ? "img" : undefined}
      {...rest}
    />
  );
}
