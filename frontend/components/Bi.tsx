import type { ReactNode } from "react";

/**
 * Renders both languages into the DOM and lets CSS pick which one shows
 * (html[data-lang="ar"] [data-only="en"] { display: none }, and the
 * mirror rule), exactly as docs/design/changes-screen-mockup.html does.
 * Switching languages is then an instant attribute flip on <html> with no
 * re-render and no hydration risk, instead of threading a `lang` prop
 * through every piece of text in the tree.
 */
export function Bi({ en, ar }: { en: ReactNode; ar: ReactNode }) {
  return (
    <>
      <span data-only="en">{en}</span>
      <span data-only="ar">{ar}</span>
    </>
  );
}
