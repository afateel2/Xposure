/**
 * Keeps clause numbers such as 2-5-3-9 or 2.13.3.4 readable inside Arabic text:
 * each dotted or dashed number run is isolated and forced left-to-right so the
 * bidi algorithm does not reverse it.
 */
export function Isolated({ text }: { text: string }) {
  const parts = text.split(/(\d+(?:[-.]\d+)+)/g);
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <bdi key={i} dir="ltr">{part}</bdi>
        ) : (
          part
        ),
      )}
    </>
  );
}
