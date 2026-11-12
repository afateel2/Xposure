/** Types for the Facility profile (backend/app/routes/company.py, backend/app/company/). */

export type FileKind = "policy" | "procedure" | "evidence" | "system" | "other";
export type FileOrigin = "baseline" | "agent" | "revert";
export type NodeStatus = "up_to_date" | "action_required" | "assigned" | "updated_by_agent";

export interface CompanyProfile {
  name_en: string;
  name_ar: string;
  sector_en: string;
  sector_ar: string;
  location_en: string;
  location_ar: string;
  site: string;
  applied_regulation: string;
  employees?: number;
  products?: { name: string; sku?: string; description_en?: string; description_ar?: string }[];
  regulators_tracked?: { code: string; name_en: string; name_ar: string }[];
}

export interface CompanyOverview {
  profile: CompanyProfile;
  applied_regulation: string | null;
  known_regulation_versions: string[];
  counts: { files: number; nodes: number; open_actions: number; assigned_actions: number; agent_edited_files: number };
}

export interface CompanyFile {
  path: string;
  name: string;
  kind: FileKind;
  size: number;
  version: string | null;
  last_modified: string;
  last_origin: FileOrigin;
  version_count: number;
  agent_edited: boolean;
}

export interface FileVersion {
  n: number;
  doc_version: string | null;
  origin: FileOrigin;
  timestamp: string;
  sha256: string;
  size: number;
  action_id: number | null;
  note: string | null;
  reverted_to?: number;
}

export interface FileDiff {
  from_n: number;
  to_n: number;
  from_version: string | null;
  to_version: string | null;
  added: number;
  removed: number;
  unified: string;
}

export interface FileDetail extends CompanyFile {
  content: string;
  content_version_n: number;
  versions: FileVersion[];
  diff: FileDiff | null;
  nodes: { id: number; name: string; type: string }[];
  reverted_to_n?: number;
  actions_marked?: number[];
}

export interface CompanyNode {
  id: number;
  type: string;
  display_type: string;
  type_label_en: string;
  type_label_ar: string;
  name: string;
  attrs: Record<string, unknown>;
  owner: { id: number; name: string; email: string | null; role: string | null } | null;
  file: string | null;
  config_file: string | null;
  path: string | null;
  version: string | null;
  last_modified: string | null;
  last_origin: FileOrigin | null;
  status: NodeStatus;
  status_label_en: string;
  status_label_ar: string;
  open_action_count: number;
  assigned_action_count: number;
  agent_edit_count: number;
  last_agent_edit: string | null;
  change_ids: number[];
  open_change_ids: number[];
}

export interface CompanyNodes {
  nodes: CompanyNode[];
  counts_by_status: Partial<Record<NodeStatus, number>>;
}
