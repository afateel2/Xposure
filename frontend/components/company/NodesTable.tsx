"use client";

import { useMemo, useState } from "react";
import { Bi } from "@/components/Bi";
import { RelTime } from "@/components/RelTime";
import { BrandMotif, Button, Card, DataTable, Icon, Segmented } from "@/components/ui";
import { Workflow } from "lucide-react";
import type { CompanyNode } from "@/lib/types-company";
import { NodeStatusBadge } from "./labels";

type Group = "all" | "documents" | "products" | "processes" | "owners" | "other";

function groupOf(n: CompanyNode): Exclude<Group, "all"> {
  switch (n.display_type) {
    case "policy":
    case "procedure":
    case "evidence":
      return "documents";
    case "product":
      return "products";
    case "process":
      return "processes";
    case "owner":
      return "owners";
    default:
      return "other";
  }
}

const GROUP_LABEL: Record<Group, { en: string; ar: string }> = {
  all: { en: "All", ar: "الكل" },
  documents: { en: "Documents", ar: "الوثائق" },
  products: { en: "Products", ar: "المنتجات" },
  processes: { en: "Processes", ar: "العمليات" },
  owners: { en: "Owners", ar: "المسؤولون" },
  other: { en: "Other", ar: "أخرى" },
};

/**
 * The company's org nodes (owners, systems, processes, products, documents)
 * with the status derived by the backend from the action queue and the file
 * history. A node that maps to a company file links to it in the viewer.
 */
export function NodesTable({
  nodes, loading, error, onOpenFile,
}: {
  nodes: CompanyNode[] | null;
  loading: boolean;
  error: boolean;
  onOpenFile: (path: string) => void;
}) {
  const [group, setGroup] = useState<Group>("all");
  const list = useMemo(() => nodes ?? [], [nodes]);
  const groups = useMemo(() => {
    const present = new Set(list.map(groupOf));
    return (["all", "documents", "products", "processes", "owners", "other"] as Group[]).filter((g) => g === "all" || present.has(g as Exclude<Group, "all">));
  }, [list]);
  const active = groups.includes(group) ? group : "all";
  const shown = active === "all" ? list : list.filter((n) => groupOf(n) === active);

  return (
    <Card
      title={<Bi en="Company nodes" ar="عناصر الشركة" />}
      icon={<Icon icon={Workflow} size={18} />}
      className="fac-nodes"
      pad={false}
      actions={groups.length > 2 ? (
        <Segmented<Group> value={active} onChange={setGroup} ariaLabel="Node type" options={groups.map((g) => ({ value: g, label: <Bi en={GROUP_LABEL[g].en} ar={GROUP_LABEL[g].ar} /> }))} />
      ) : null}
    >
      {loading && !nodes ? (
        <BrandMotif variant="spinner" compact title={<Bi en="Loading nodes" ar="جارٍ تحميل العناصر" />} />
      ) : error && !nodes ? (
        <BrandMotif variant="empty" compact title={<Bi en="The nodes could not be loaded" ar="تعذّر تحميل العناصر" />} />
      ) : shown.length === 0 ? (
        <BrandMotif variant="empty" compact title={<Bi en="No nodes to show" ar="لا توجد عناصر للعرض" />} />
      ) : (
        <div className="fac-nodes-table">
          <DataTable caption={<Bi en="Company nodes and their status" ar="عناصر الشركة وحالتها" />}>
            <thead>
              <tr>
                <th><Bi en="Name" ar="الاسم" /></th>
                <th><Bi en="Type" ar="النوع" /></th>
                <th><Bi en="Owner" ar="المسؤول" /></th>
                <th><Bi en="Document" ar="الوثيقة" /></th>
                <th><Bi en="Status" ar="الحالة" /></th>
                <th className="num"><Bi en="Open actions" ar="إجراءات مفتوحة" /></th>
                <th><Bi en="Last change" ar="آخر تغيير" /></th>
              </tr>
            </thead>
            <tbody>
              {shown.map((n) => (
                <tr key={n.id}>
                  <td className="fac-node-name"><bdi>{n.name}</bdi></td>
                  <td><Bi en={n.type_label_en} ar={n.type_label_ar} /></td>
                  <td>{n.owner ? <bdi>{n.owner.name}</bdi> : <span className="xp-muted">-</span>}</td>
                  <td>
                    {n.path ? (
                      <Button variant="link" size="sm" onClick={() => onOpenFile(n.path as string)}>
                        <span className="mono" dir="ltr">{(n.path as string).split("/").pop()}</span>
                      </Button>
                    ) : <span className="xp-muted">-</span>}
                  </td>
                  <td><NodeStatusBadge status={n.status} /></td>
                  <td className="num">
                    {n.open_action_count + n.assigned_action_count > 0 ? (
                      <span>
                        <bdi>{n.open_action_count}</bdi>
                        {n.assigned_action_count > 0 && (
                          <span className="xp-muted"> + <bdi>{n.assigned_action_count}</bdi> <Bi en="assigned" ar="مُسنَدة" /></span>
                        )}
                      </span>
                    ) : <span className="xp-muted">0</span>}
                  </td>
                  <td className="fac-node-when">
                    {n.last_agent_edit ? <RelTime iso={n.last_agent_edit} /> : n.last_modified ? <RelTime iso={n.last_modified} /> : <span className="xp-muted">-</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </div>
      )}
    </Card>
  );
}
