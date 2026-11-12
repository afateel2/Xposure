import Image from "next/image";

/**
 * The Xposure wordmark: a monochrome raster (X shattering into a camera lens
 * standing in for the "p", then "osure" in outline), extracted from the design
 * system HTML into /public/brand/xposure-logo.jpg. Rendered from a cropped,
 * transparent PNG derived from it (xposure-logo.png, ink on alpha) so the
 * design system rule works on any surface: black on light, `filter: invert(1)`
 * on dark. The mark is never recoloured.
 *
 * `size` is the rendered HEIGHT in px (kept from the previous API). Pass
 * `inverted` to force the dark-surface treatment (the sidebar does, because it
 * is navy in both themes); otherwise it follows the theme via --logo-filter.
 */
export function Logo({ size = 40, inverted = false, className }: { size?: number; inverted?: boolean; className?: string }) {
  const width = Math.round(size * (844 / 400));
  return (
    <Image
      src="/brand/xposure-logo.png"
      alt="Xposure"
      width={width}
      height={size}
      priority
      unoptimized
      className={className}
      style={{ ...(className ? { width: "auto" } : { height: size, width: "auto" }), filter: inverted ? "invert(1)" : "var(--logo-filter)" }}
    />
  );
}
