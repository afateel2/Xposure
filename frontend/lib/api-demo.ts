import { apiJson } from "./api-http";
import type { ActivityFeed, AgentStateLite, DemoRun, DemoStatus, ScanStarted } from "./types-demo";

export const getDemoRun = (signal?: AbortSignal) => apiJson<DemoRun>("/demo/run", { signal });
export const getDemoStatus = (signal?: AbortSignal) => apiJson<DemoStatus>("/demo/status", { signal });
export const startDemoScan = () => apiJson<ScanStarted>("/demo/scan", { method: "POST" });
export const resetDemo = () => apiJson<Record<string, unknown>>("/demo/reset", { method: "POST" });
export const getActivity = (limit: number, signal?: AbortSignal) => apiJson<ActivityFeed>(`/activity?limit=${limit}`, { signal });
export const getAgentState = (signal?: AbortSignal) => apiJson<AgentStateLite>("/agent/state", { signal });
