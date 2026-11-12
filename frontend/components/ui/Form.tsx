import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

/**
 * Form field wrapper: label above the control, optional hint, error text in
 * danger. Pass `invalid` to the control to get the danger border.
 *
 *   <Field label={<Bi .../>} error={err ? <Bi .../> : null}><Input invalid={!!err} /></Field>
 */
export function Field({
  label, htmlFor, hint, error, children, className,
}: {
  label?: ReactNode;
  htmlFor?: string;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`xp-field${className ? ` ${className}` : ""}`}>
      {label && <label className="xp-label" htmlFor={htmlFor}>{label}</label>}
      {children}
      {error ? <span className="xp-error" role="alert">{error}</span> : hint ? <span className="xp-hint">{hint}</span> : null}
    </div>
  );
}

const cx = (base: string, invalid?: boolean, extra?: string) => [base, invalid ? "is-error" : "", extra ?? ""].filter(Boolean).join(" ");

export function Input({ invalid, className, ...rest }: InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }) {
  return <input className={cx("xp-input", invalid, className)} aria-invalid={invalid || undefined} {...rest} />;
}

export function Select({ invalid, className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement> & { invalid?: boolean }) {
  return (
    <select className={cx("xp-select", invalid, className)} aria-invalid={invalid || undefined} {...rest}>
      {children}
    </select>
  );
}

export function Textarea({ invalid, className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }) {
  return <textarea className={cx("xp-textarea", invalid, className)} aria-invalid={invalid || undefined} {...rest} />;
}

export function Checkbox({ children, className, ...rest }: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { children?: ReactNode }) {
  return (
    <label className={`xp-check${className ? ` ${className}` : ""}`}>
      <input type="checkbox" {...rest} />
      <span>{children}</span>
    </label>
  );
}
