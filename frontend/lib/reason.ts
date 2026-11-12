/**
 * A dismissal always carries a written reason (backend/app/routes/actions.py
 * enforces the same limits). Shared by the dismiss dialog and the bulk
 * command pad so the rule is written down once.
 */
export const MIN_REASON_CHARS = 3;
export const MAX_REASON_CHARS = 500;

/** Collapse whitespace and cap the length, exactly as the backend does. */
export function cleanReason(text: string): string {
  return text.split(/\s+/).filter(Boolean).join(" ").slice(0, MAX_REASON_CHARS);
}

export function reasonIsValid(text: string): boolean {
  return cleanReason(text).length >= MIN_REASON_CHARS;
}
