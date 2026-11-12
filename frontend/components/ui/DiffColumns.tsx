import type { ReactNode } from "react";

/** Removed text: red, struck through, prefixed with a minus. Use inside DiffColumns. */
export function Del({ children }: { children: ReactNode }) {
  return <span className="diff-del">{children}</span>;
}

/** Added text: green, underlined, prefixed with a plus. Use inside DiffColumns. */
export function Add({ children }: { children: ReactNode }) {
  return <span className="diff-add">{children}</span>;
}

/**
 * Before/after columns. In RTL the "before" column sits at the start (right),
 * in LTR at the left. Put <Del> and <Add> spans inside the children.
 */
export function DiffColumns({
  beforeLabel, afterLabel, before, after, className,
}: {
  beforeLabel: ReactNode;
  afterLabel: ReactNode;
  before: ReactNode;
  after: ReactNode;
  className?: string;
}) {
  return (
    <div className={`xp-diff${className ? ` ${className}` : ""}`}>
      <div className="xp-diff-col">
        <div className="xp-diff-label">{beforeLabel}</div>
        <p>{before}</p>
      </div>
      <div className="xp-diff-col">
        <div className="xp-diff-label">{afterLabel}</div>
        <p>{after}</p>
      </div>
    </div>
  );
}
