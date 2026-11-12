import { useSyncExternalStore } from "react";

/**
 * Tiny store the app shell (sidebar badges, notification bell) reads from.
 * Any page or hook can feed it without prop drilling:
 *
 *   setNavBadge("changes", 19);         // red count on the Changes item
 *   setNavBadge("tasks", 3);            // orange count on the Tasks item
 *   setNavBadge("changes", null);       // hide the badge
 *   setNotificationCount(4);            // bell badge without item details
 *   setNotifications([{ id: "a", en: "...", ar: "...", href: "/changes/12" }]);
 *
 * Defaults: everything hidden. Nothing here fetches data by itself.
 */
export type NavBadgeKey = "changes" | "tasks";

export interface ShellNotification {
  id: string;
  en: string;
  ar: string;
  href?: string;
}

export interface ShellState {
  badges: Partial<Record<NavBadgeKey, number>>;
  notifications: ShellNotification[];
  /** Explicit bell count; when null the count is notifications.length. */
  notificationCount: number | null;
}

const EMPTY: ShellState = { badges: {}, notifications: [], notificationCount: null };
let state: ShellState = EMPTY;
const listeners = new Set<() => void>();

function commit(next: ShellState) {
  state = next;
  listeners.forEach((l) => l());
}

export function setNavBadge(key: NavBadgeKey, count: number | null | undefined): void {
  const badges = { ...state.badges };
  if (count == null || count <= 0) delete badges[key];
  else badges[key] = Math.round(count);
  commit({ ...state, badges });
}

export function setNotifications(items: ShellNotification[]): void {
  commit({ ...state, notifications: items });
}

export function setNotificationCount(count: number | null): void {
  commit({ ...state, notificationCount: count == null ? null : Math.max(0, Math.round(count)) });
}

export function useShellState(): ShellState {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => state,
    () => EMPTY,
  );
}
