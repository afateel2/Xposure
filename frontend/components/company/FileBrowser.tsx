"use client";

import { Bi } from "@/components/Bi";
import { RelTime } from "@/components/RelTime";
import { BrandMotif, Card, FileText, Icon } from "@/components/ui";
import { FileCode } from "lucide-react";
import type { CompanyFile, FileKind } from "@/lib/types-company";
import { AgentChip, KIND_LABEL, KIND_ORDER, fmtSize } from "./labels";

/**
 * "Governance documents": the company's policies, procedures, evidence and
 * system settings, grouped by kind. Each file shows its document version,
 * how many versions exist, when it last changed, its size, and a chip when
 * the last version was written by the agent.
 */
export function FileBrowser({
  files, selected, onSelect, loading, error,
}: {
  files: CompanyFile[] | null;
  selected: string | null;
  onSelect: (path: string) => void;
  loading: boolean;
  error: boolean;
}) {
  const groups = KIND_ORDER.map((kind) => ({ kind, items: (files ?? []).filter((f) => f.kind === kind) })).filter((g) => g.items.length > 0);

  return (
    <Card
      title={<Bi en="Governance documents" ar="وثائق الحوكمة" />}
      icon={<Icon icon={FileText} size={18} />}
      className="fac-browser"
      pad={false}
    >
      {loading && !files ? (
        <BrandMotif variant="spinner" compact title={<Bi en="Loading documents" ar="جارٍ تحميل الوثائق" />} />
      ) : error && !files ? (
        <BrandMotif variant="empty" compact title={<Bi en="The documents could not be loaded" ar="تعذّر تحميل الوثائق" />} hint={<Bi en="The backend did not answer. Try again in a moment." ar="لم يستجب الخادم. أعد المحاولة بعد قليل." />} />
      ) : groups.length === 0 ? (
        <BrandMotif variant="empty" compact title={<Bi en="No documents yet" ar="لا توجد وثائق بعد" />} />
      ) : (
        groups.map((g) => (
          <section key={g.kind} className="fac-group" aria-label={KIND_LABEL[g.kind as FileKind].plural.en}>
            <h4 className="fac-group-title">
              <Bi en={KIND_LABEL[g.kind].plural.en} ar={KIND_LABEL[g.kind].plural.ar} />
              <span className="fac-group-count tabular">{g.items.length}</span>
            </h4>
            <ul className="fac-files">
              {g.items.map((f) => {
                const active = f.path === selected;
                return (
                  <li key={f.path}>
                    <button type="button" className={`fac-file${active ? " is-selected" : ""}`} aria-current={active ? "true" : undefined} onClick={() => onSelect(f.path)}>
                      <span className="fac-file-icon" aria-hidden="true"><Icon icon={f.name.endsWith(".yaml") ? FileCode : FileText} size={16} /></span>
                      <span className="fac-file-main">
                        <span className="fac-file-name"><bdi>{f.name}</bdi></span>
                        <span className="fac-file-meta">
                          <span className="fac-file-ver tabular" dir="ltr">v{f.version ?? "?"}</span>
                          {f.version_count > 1 && (
                            <span><bdi className="tabular">{f.version_count}</bdi> <Bi en="versions" ar="إصدارات" /></span>
                          )}
                          <RelTime iso={f.last_modified} />
                          <span className="tabular" dir="ltr">{fmtSize(f.size)}</span>
                        </span>
                        {f.agent_edited && <AgentChip />}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        ))
      )}
    </Card>
  );
}
