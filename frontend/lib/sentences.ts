// Mirrors app/diff.py's _SENTENCE_BOUNDARY exactly, so the client can
// re-split old/new clause text the same way the backend did when it
// produced diff_ops (change.diff_spans_json) — diff_ops carries only the
// sentences that changed (equal spans are omitted, see sentence_delta()'s
// docstring), so the UI re-splits the full text and marks whichever
// sentences match, rather than the backend needing to also ship full
// span offsets it does not otherwise need.
const SENTENCE_BOUNDARY = /(?<=[.!?])\s+/;

export function splitSentences(text: string | null | undefined): string[] {
  if (!text) return [];
  return text
    .split(SENTENCE_BOUNDARY)
    .map((s) => s.trim())
    .filter(Boolean);
}
