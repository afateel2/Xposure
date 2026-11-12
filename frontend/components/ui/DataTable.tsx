import type { ReactNode } from "react";

/**
 * Table shell: a scrollable, bordered wrapper plus the `xp-table` styles
 * (start-aligned headers, zebra rows, hover, mono cells via className="mono",
 * numeric cells via className="num", clickable rows via className="is-clickable").
 *
 *   <DataTable>
 *     <thead><tr><th>..</th></tr></thead>
 *     <tbody>...</tbody>
 *   </DataTable>
 */
export function DataTable({ children, className, caption }: { children: ReactNode; className?: string; caption?: ReactNode }) {
  return (
    <div className="xp-table-wrap">
      <table className={`xp-table${className ? ` ${className}` : ""}`}>
        {caption && <caption className="sr-only">{caption}</caption>}
        {children}
      </table>
    </div>
  );
}
