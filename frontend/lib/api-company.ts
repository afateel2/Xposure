import { apiJson } from "./api-http";
import type { CompanyFile, CompanyNodes, CompanyOverview, FileDetail } from "./types-company";

/** Encodes each path segment but keeps the slashes (the proxy splits on them). */
const filePath = (path: string) => path.split("/").map(encodeURIComponent).join("/");

export const getCompany = (signal?: AbortSignal) => apiJson<CompanyOverview>("/company", { signal });
export const getCompanyNodes = (signal?: AbortSignal) => apiJson<CompanyNodes>("/company/nodes", { signal });
export const getCompanyFiles = (signal?: AbortSignal) => apiJson<{ files: CompanyFile[] }>("/company/files", { signal });
export const getCompanyFile = (path: string, version?: number, signal?: AbortSignal) =>
  apiJson<FileDetail>(`/company/files/${filePath(path)}${version != null ? `?version=${version}` : ""}`, { signal });
export const revertCompanyFile = (path: string) =>
  apiJson<FileDetail>(`/company/files/${filePath(path)}/revert`, { method: "POST" });
