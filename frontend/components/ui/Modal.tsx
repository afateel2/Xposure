"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";

/**
 * Design system modal on the native <dialog> element: focus is trapped, Esc
 * closes, focus returns to the trigger, and the backdrop is styled by
 * `dialog.xp-modal::backdrop`. Controlled: keep `open` in your state and
 * clear it in `onClose`.
 *
 *   <Modal open={open} onClose={() => setOpen(false)} title={<Bi .../>}
 *          footer={<><Button variant="secondary">..</Button><Button variant="danger">..</Button></>}>
 *     body text
 *   </Modal>
 */
export function Modal({
  open, onClose, title, children, footer, size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  size?: "md" | "lg";
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={`xp-modal${size === "lg" ? " size-lg" : ""}`}
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
    >
      {open && (
        <>
          <div className="xp-modal-head">
            <h3 id={titleId}>{title}</h3>
          </div>
          {children != null && <div className="xp-modal-body">{children}</div>}
          {footer && <div className="xp-modal-foot">{footer}</div>}
        </>
      )}
    </dialog>
  );
}
