import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { LoaderCircle } from "lucide-react";

export type ButtonVariant = "primary" | "secondary" | "success" | "danger" | "ghost" | "link";
export type ButtonSize = "sm" | "md" | "lg";

type Common = {
  /** Exactly ONE primary (brand) button per screen area. */
  variant?: ButtonVariant;
  size?: ButtonSize;
  block?: boolean;
  /** Icon-only button: square, the caller must pass aria-label. */
  iconOnly?: boolean;
  loading?: boolean;
  /** Leading icon element, e.g. <Icon icon={Check} size={16} />. */
  icon?: ReactNode;
  className?: string;
  children?: ReactNode;
};

type ButtonProps = Common & Omit<ButtonHTMLAttributes<HTMLButtonElement>, keyof Common> & { href?: undefined };
type LinkProps = Common & { href: string; target?: string; rel?: string; "aria-label"?: string; title?: string };

/** Class string for the design system button, for styling a custom element. */
export function buttonClass({ variant = "secondary", size = "md", block, iconOnly, loading, className }: Common): string {
  return [
    "xp-btn",
    `xp-btn-${variant}`,
    size === "sm" ? "xp-btn-sm" : size === "lg" ? "xp-btn-lg" : "",
    block ? "xp-btn-block" : "",
    iconOnly ? "xp-btn-icon" : "",
    loading ? "is-loading" : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");
}

/**
 * Design system button. Variants: primary (brand), secondary, success,
 * danger, ghost (outlined brand), link. Pass `href` to render a Next link
 * with identical styling.
 */
export function Button(props: ButtonProps | LinkProps) {
  const { variant, size, block, iconOnly, loading, icon, className, children } = props;
  const cls = buttonClass({ variant, size, block, iconOnly, loading, className });
  const content = (
    <>
      {loading ? <LoaderCircle size={16} strokeWidth={2} className="xp-icon xp-spin" aria-hidden="true" /> : icon}
      {children}
    </>
  );
  if (props.href !== undefined) {
    return (
      <Link href={props.href} className={cls} target={props.target} rel={props.rel} aria-label={props["aria-label"]} title={props.title}>
        {content}
      </Link>
    );
  }
  const rest: Record<string, unknown> = { ...props };
  for (const key of ["variant", "size", "block", "iconOnly", "loading", "icon", "className", "children", "href"]) delete rest[key];
  const { type = "button", disabled, ...others } = rest as ButtonHTMLAttributes<HTMLButtonElement>;
  return (
    <button type={type} className={cls} disabled={disabled || loading} aria-busy={loading || undefined} {...others}>
      {content}
    </button>
  );
}
