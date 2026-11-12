import type { ReactNode } from "react";
import { Bi } from "@/components/Bi";

type Kind = "ctx" | "add" | "del";
interface Row {
  kind: Kind;
  oldNo: number | null;
  newNo: number | null;
  text: string;
  /** Marks the start of a new hunk (rows before it are not adjacent). */
  gap?: boolean;
}

/** Parses the backend's unified diff (difflib, no trailing newlines). Header lines are skipped. */
export function parseUnified(unified: string): Row[] {
  const rows: Row[] = [];
  let oldNo = 0;
  let newNo = 0;
  let firstHunk = true;
  let pendingGap = false;
  for (const raw of unified.split("\n")) {
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(raw);
    if (hunk) {
      oldNo = Number(hunk[1]);
      newNo = Number(hunk[2]);
      pendingGap = !firstHunk;
      firstHunk = false;
      continue;
    }
    if (raw.startsWith("--- ") || raw.startsWith("+++ ") || firstHunk) continue;
    const mark = raw[0];
    const text = raw.slice(1);
    let row: Row;
    if (mark === "+") row = { kind: "add", oldNo: null, newNo: newNo++, text };
    else if (mark === "-") row = { kind: "del", oldNo: oldNo++, newNo: null, text };
    else if (mark === " " || raw === "") row = { kind: "ctx", oldNo: oldNo++, newNo: newNo++, text };
    else continue;
    if (pendingGap) {
      row.gap = true;
      pendingGap = false;
    }
    rows.push(row);
  }
  return rows;
}

const TOKEN = /\s+|[^\s]+/g;

/** Word level diff of two lines: which tokens of each side are not shared (LCS over tokens). */
function wordDiff(a: string, b: string): { a: [string, boolean][]; b: [string, boolean][] } {
  const ta = a.match(TOKEN) ?? [];
  const tb = b.match(TOKEN) ?? [];
  if (ta.length * tb.length > 40000) return { a: [[a, true]], b: [[b, true]] };
  const dp: number[][] = Array.from({ length: ta.length + 1 }, () => new Array(tb.length + 1).fill(0));
  for (let i = ta.length - 1; i >= 0; i--) {
    for (let j = tb.length - 1; j >= 0; j--) {
      dp[i][j] = ta[i] === tb[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const outA: [string, boolean][] = [];
  const outB: [string, boolean][] = [];
  const push = (arr: [string, boolean][], tok: string, changed: boolean) => {
    const last = arr[arr.length - 1];
    if (last && last[1] === changed) last[0] += tok;
    else arr.push([tok, changed]);
  };
  let i = 0;
  let j = 0;
  while (i < ta.length && j < tb.length) {
    if (ta[i] === tb[j]) {
      push(outA, ta[i], false);
      push(outB, tb[j], false);
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      push(outA, ta[i++], true);
    } else {
      push(outB, tb[j++], true);
    }
  }
  while (i < ta.length) push(outA, ta[i++], true);
  while (j < tb.length) push(outB, tb[j++], true);
  return { a: outA, b: outB };
}

function renderParts(parts: [string, boolean][], cls: string): ReactNode {
  return parts.map(([text, changed], i) => (changed && text.trim() !== "" ? <mark key={i} className={cls}>{text}</mark> : <span key={i}>{text}</span>));
}

/**
 * Line diff with gutters (old and new line numbers), a sign column and
 * word-level highlights inside changed lines. Sign glyphs and colours are used
 * together, so the meaning never rests on colour alone. Always left to right
 * (it is a text diff), with dir="auto" on each line for Arabic passages.
 */
export function DiffView({ unified, added, removed }: { unified: string; added: number; removed: number }) {
  const rows = parseUnified(unified);
  if (rows.length === 0) {
    return (
      <p className="fac-empty-note">
        <Bi en="No differences between these two versions." ar="لا توجد فروق بين هذين الإصدارين." />
      </p>
    );
  }

  // Pair consecutive deleted and added lines for word-level highlighting.
  const marks = new Map<number, ReactNode>();
  for (let k = 0; k < rows.length; ) {
    if (rows[k].kind !== "del") {
      k++;
      continue;
    }
    let d = k;
    while (d < rows.length && rows[d].kind === "del") d++;
    let a = d;
    while (a < rows.length && rows[a].kind === "add") a++;
    const dels = d - k;
    const adds = a - d;
    if (adds > 0) {
      for (let p = 0; p < Math.min(dels, adds); p++) {
        const w = wordDiff(rows[k + p].text, rows[d + p].text);
        marks.set(k + p, renderParts(w.a, "fac-w-del"));
        marks.set(d + p, renderParts(w.b, "fac-w-add"));
      }
    }
    k = a;
  }

  return (
    <div className="fac-diff-wrap">
      <div className="fac-diff-stats" aria-label="Diff summary">
        <span className="fac-stat-add tabular">+{added}</span>
        <span className="fac-stat-del tabular">&minus;{removed}</span>
        <span className="fac-diff-stats-text"><Bi en="lines added and removed" ar="سطرًا مضافًا ومحذوفًا" /></span>
      </div>
      <div className="fac-diff-scroll" dir="ltr" tabIndex={0} role="region" aria-label="File changes">
        <table className="fac-diff">
          <tbody>
            {rows.map((r, idx) => (
              <tr key={idx} className={`fac-diff-row is-${r.kind}${r.gap ? " has-gap" : ""}`}>
                <td className="fac-diff-no" aria-hidden="true">{r.oldNo ?? ""}</td>
                <td className="fac-diff-no" aria-hidden="true">{r.newNo ?? ""}</td>
                <td className="fac-diff-sign">
                  <span aria-hidden="true">{r.kind === "add" ? "+" : r.kind === "del" ? "−" : ""}</span>
                  <span className="sr-only">{r.kind === "add" ? "Added: " : r.kind === "del" ? "Removed: " : ""}</span>
                </td>
                <td className="fac-diff-text" dir="auto">{marks.get(idx) ?? (r.text === "" ? " " : r.text)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
