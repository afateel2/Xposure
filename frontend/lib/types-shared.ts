/**
 * Types shared by the agent file edit, ERP task and visibility feed features. Kept in a separate file so several pages can import them
 * without editing lib/types.ts. Mirrors the backend response shapes.
 */

/** Agent file edit stored on Action.payload_json["effect"] (see backend/app/company/executor.py). */
export interface ActionEffect {
  kind: "file_edit";
  path: string;
  version_before: number;
  version_after: number;
  added: number;
  removed: number;
  diff_unified: string;
  executed_at?: string;
  cached?: boolean;
  [key: string]: unknown;
}

/** ERP task stored on Action.payload_json["erp"] (see backend/app/erp/). */
export interface ErpInfo {
  system: "odoo";
  task_id: number;
  url: string;
  stage: string;
  stage_key?: "new" | "in_progress" | "waiting" | "done";
  assignee: string | null;
  synced_at: string | null;
}

export interface ErpEmployee {
  id: number;
  name: string;
  job_title: string | null;
  work_email: string | null;
  department: string | null;
}

export interface ErpStatus {
  configured: boolean;
  reachable: boolean;
  system: "odoo";
  version?: string | null;
  database?: string | null;
  url?: string | null;
  message_en: string;
  message_ar: string;
}
