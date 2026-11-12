"use client";

import { useMemo } from "react";
import { useLang, t } from "@/lib/lang";

type LineKind = "hunk" | "add" | "del" | "ctx";
interface DiffLine {
  kind: LineKind;
  text: string;
  oldNo: number | null;
  newNo: number | null;
}

/** Parses a unified diff (the executor's `diff_unified`) into numbered lines. Header lines are dropped. */
export function parseUnifiedDiff(diff: string): DiffLine[] {
  const out: DiffLine[] = [];
  let oldNo = 0;
  let newNo = 0;
  let inHunk = false;
  for (const raw of diff.replace(/\r\n/g, "\n").split("\n")) {
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$/.exec(raw);
    if (hunk) {
      inHunk = true;
      oldNo = Number(hunk[1]);
      newNo = Number(hunk[2]);
      out.push({ kind: "hunk", text: raw, oldNo: null, newNo: null });
      continue;
    }
    if (!inHunk) continue; // ---/+++ file headers before the first hunk
    if (raw.startsWith("\\")) continue; // "\ No newline at end of file"
    if (raw.startsWith("+")) out.push({ kind: "add", text: raw.slice(1), oldNo: null, newNo: newNo++ });
    else if (raw.startsWith("-")) out.push({ kind: "del", text: raw.slice(1), oldNo: oldNo++, newNo: null });
    else if (raw.startsWith(" ")) out.push({ kind: "ctx", text: raw.slice(1), oldNo: oldNo++, newNo: newNo++ });
    else if (raw === "") continue;
  }
  return out;
}

/**
 * Unified diff with line-number gutters and add/remove colouring (same green
 * and red as the clause diff). Always left-to-right monospace: it is code.
 */
export function DiffViewer({ diff, maxBlockSize = 380 }: { diff: string; maxBlockSize?: number }) {
  const lang = useLang();
  const lines = useMemo(() => parseUnifiedDiff(diff), [diff]);
  if (lines.length === 0) {
    return <div className="eff-diff-empty">{t(lang, "The diff is empty.", "لا توجد فروقات لعرضها.")}</div>;
  }
  return (
    <div
      className="eff-diff"
      dir="ltr"
      role="region"
      tabIndex={0}
      aria-label={t(lang, "Unified diff of the file edit", "الفروقات الموحّدة لتعديل الملف")}
      style={{ maxBlockSize }}
    >
      {lines.map((line, i) =>
        line.kind === "hunk" ? (
          <div key={i} className="eff-line is-hunk">
            <span className="eff-no" aria-hidden="true" />
            <span className="eff-no" aria-hidden="true" />
            <span className="eff-sign" aria-hidden="true" />
            <code className="eff-text">{line.text}</code>
          </div>
        ) : (
          <div key={i} className={`eff-line is-${line.kind}`}>
            <span className="eff-no tabular" aria-hidden="true">{line.oldNo ?? ""}</span>
            <span className="eff-no tabular" aria-hidden="true">{line.newNo ?? ""}</span>
            <span className="eff-sign">{line.kind === "add" ? "+" : line.kind === "del" ? "−" : ""}</span>
            <code className="eff-text">{line.text === "" ? " " : line.text}</code>
          </div>
        ),
      )}
    </div>
  );
}
