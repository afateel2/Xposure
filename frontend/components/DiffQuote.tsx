import type { DiffOp } from "@/lib/types";
import { splitSentences } from "@/lib/sentences";
import { Add, Del, DiffColumns } from "@/components/ui";
import { Bi } from "./Bi";

/**
 * One side of the "diff receipt" (docs/design/DESIGN_DIRECTION.md): the full
 * clause text with whichever sentences changed highlighted (removed text red,
 * added text green, via the design system Del/Add). `text_ar` is empty for
 * every clause today (source PDFs are English-only), so the quote is always
 * shown in English regardless of the language toggle, labeled as such.
 */
export function ClauseText({
  text,
  changedSentences,
  variant,
}: {
  text: string | null;
  changedSentences: Set<string>;
  variant: "old" | "new";
}) {
  const sentences = splitSentences(text);
  if (sentences.length === 0) {
    return (
      <span className="chg-quote-empty">
        <Bi
          en={variant === "old" ? "[no counterpart in the old version]" : "[no counterpart in the new version]"}
          ar={variant === "old" ? "[لا يوجد مقابل في النسخة السابقة]" : "[لا يوجد مقابل في النسخة الجديدة]"}
        />
      </span>
    );
  }
  return (
    <span className="chg-quote" dir="ltr">
      {sentences.map((sentence, i) => {
        const changed = changedSentences.has(sentence);
        const Wrap = changed ? (variant === "old" ? Del : Add) : null;
        return (
          <span key={i}>
            {Wrap ? <Wrap>{sentence}</Wrap> : sentence}
            {i < sentences.length - 1 ? " " : ""}
          </span>
        );
      })}
    </span>
  );
}

function SideLabel({ en, ar }: { en: string; ar: string }) {
  return (
    <span className="chg-quote-label">
      <Bi en={en} ar={ar} />
      <span className="lang-mark">EN · source</span>
    </span>
  );
}

/** Old vs new clause as design system DiffColumns, changed sentences marked. */
export function ClauseDiff({
  oldText,
  newText,
  ops,
  oldLabel,
  newLabel,
}: {
  oldText: string | null;
  newText: string | null;
  ops: DiffOp[];
  oldLabel: string | null;
  newLabel: string | null;
}) {
  const oldChanged = collectChangedSentences(ops, "old");
  const newChanged = collectChangedSentences(ops, "new");
  return (
    <DiffColumns
      beforeLabel={<SideLabel en={`Previous text · ${oldLabel ?? "?"}`} ar={`النص السابق · ${oldLabel ?? "؟"}`} />}
      afterLabel={<SideLabel en={`New text · ${newLabel ?? "?"}`} ar={`النص الجديد · ${newLabel ?? "؟"}`} />}
      before={<ClauseText text={oldText} changedSentences={oldChanged} variant="old" />}
      after={<ClauseText text={newText} changedSentences={newChanged} variant="new" />}
    />
  );
}

export function collectChangedSentences(ops: DiffOp[], side: "old" | "new"): Set<string> {
  const set = new Set<string>();
  for (const op of ops) {
    for (const sentence of op[side]) set.add(sentence);
  }
  return set;
}
