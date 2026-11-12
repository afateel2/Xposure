"use client";

import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { CircleAlert, CircleCheck, CircleX, Info, X } from "lucide-react";
import { Bi } from "../Bi";

export type ToastKind = "success" | "error" | "info" | "warning";

interface ToastItem {
  id: number;
  kind: ToastKind;
  message: ReactNode;
}

export interface ToastApi {
  /** Shows a toast. `message` may be <Bi en=.. ar=.. />. Auto-dismisses. */
  toast: (message: ReactNode, opts?: { kind?: ToastKind; duration?: number }) => number;
  success: (message: ReactNode) => number;
  error: (message: ReactNode) => number;
  info: (message: ReactNode) => number;
  warning: (message: ReactNode) => number;
  dismiss: (id: number) => void;
}

const NOOP_API: ToastApi = {
  toast: () => 0, success: () => 0, error: () => 0, info: () => 0, warning: () => 0, dismiss: () => undefined,
};

const ToastContext = createContext<ToastApi>(NOOP_API);

const KIND_ICON = { success: CircleCheck, error: CircleX, info: Info, warning: CircleAlert } as const;
const KIND_TONE: Record<ToastKind, string> = { success: "tone-success", error: "tone-danger", info: "tone-info", warning: "tone-warning" };

/** Mounted once in the app shell (AppShell). Use `useToast()` anywhere below it. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => setItems((cur) => cur.filter((t) => t.id !== id)), []);

  const toast = useCallback<ToastApi["toast"]>(
    (message, opts) => {
      const id = nextId.current++;
      const kind = opts?.kind ?? "info";
      setItems((cur) => [...cur.slice(-3), { id, kind, message }]);
      const duration = opts?.duration ?? (kind === "error" ? 8000 : 5000);
      if (duration > 0) window.setTimeout(() => dismiss(id), duration);
      return id;
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      toast,
      success: (m) => toast(m, { kind: "success" }),
      error: (m) => toast(m, { kind: "error" }),
      info: (m) => toast(m, { kind: "info" }),
      warning: (m) => toast(m, { kind: "warning" }),
      dismiss,
    }),
    [toast, dismiss],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="xp-toasts" role="region" aria-live="polite" aria-label="Notifications">
        {items.map((t) => {
          const Glyph = KIND_ICON[t.kind];
          return (
            <div key={t.id} className={`xp-toast ${KIND_TONE[t.kind]}`} role={t.kind === "error" ? "alert" : "status"}>
              <Glyph size={18} strokeWidth={2} className="xp-icon" aria-hidden="true" />
              <div className="xp-toast-body">{t.message}</div>
              <button type="button" className="xp-toast-close" onClick={() => dismiss(t.id)}>
                <X size={14} strokeWidth={2} aria-hidden="true" />
                <span className="sr-only"><Bi en="Dismiss" ar="إغلاق" /></span>
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

/** Returns { toast, success, error, info, warning, dismiss }. Safe (no-op) without a provider. */
export function useToast(): ToastApi {
  return useContext(ToastContext);
}
