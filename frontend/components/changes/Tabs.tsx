"use client";

import { useRef, type KeyboardEvent, type ReactNode } from "react";

export interface TabItem<T extends string> {
  value: T;
  label: ReactNode;
  count?: number | null;
  icon?: ReactNode;
}

export function tabId(prefix: string, value: string) {
  return `${prefix}-tab-${value}`;
}
export function panelId(prefix: string, value: string) {
  return `${prefix}-panel-${value}`;
}

/**
 * Accessible tab list (roving tabindex, arrow keys that follow the reading
 * direction, Home/End). Render each panel yourself with role="tabpanel",
 * id={panelId(prefix, value)} and aria-labelledby={tabId(prefix, value)}.
 */
export function Tabs<T extends string>({
  value, onChange, tabs, ariaLabel, prefix,
}: {
  value: T;
  onChange: (next: T) => void;
  tabs: TabItem<T>[];
  ariaLabel: string;
  prefix: string;
}) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  function focusTab(next: T) {
    onChange(next);
    refs.current[next]?.focus();
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const idx = tabs.findIndex((t) => t.value === value);
    if (idx < 0) return;
    const rtl = document.documentElement.getAttribute("dir") === "rtl";
    const forward = rtl ? "ArrowLeft" : "ArrowRight";
    const backward = rtl ? "ArrowRight" : "ArrowLeft";
    if (e.key === forward) {
      e.preventDefault();
      focusTab(tabs[(idx + 1) % tabs.length].value);
    } else if (e.key === backward) {
      e.preventDefault();
      focusTab(tabs[(idx - 1 + tabs.length) % tabs.length].value);
    } else if (e.key === "Home") {
      e.preventDefault();
      focusTab(tabs[0].value);
    } else if (e.key === "End") {
      e.preventDefault();
      focusTab(tabs[tabs.length - 1].value);
    }
  }

  return (
    <div className="chg-tabs" role="tablist" aria-label={ariaLabel} onKeyDown={onKeyDown}>
      {tabs.map((tab) => {
        const selected = tab.value === value;
        return (
          <button
            key={tab.value}
            ref={(el) => { refs.current[tab.value] = el; }}
            type="button"
            role="tab"
            id={tabId(prefix, tab.value)}
            aria-selected={selected}
            aria-controls={panelId(prefix, tab.value)}
            tabIndex={selected ? 0 : -1}
            className="chg-tab"
            onClick={() => onChange(tab.value)}
          >
            {tab.icon}
            <span>{tab.label}</span>
            {tab.count != null && <span className="chg-tab-count tabular">{tab.count}</span>}
          </button>
        );
      })}
    </div>
  );
}
