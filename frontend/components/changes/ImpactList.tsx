"use client";

import { useMemo } from "react";
import { Bi } from "@/components/Bi";
import { Badge, Icon } from "@/components/ui";
import { SCOPE_MATCH_LABEL } from "@/lib/labels";
import type { ImpactOut } from "@/lib/types";
import { ActionCard, type ActionCardProps, type BusyKind, type RevertedEffect } from "./ActionCard";
import type { ErpErrorNote } from "./erp-types";
import { Isolated } from "./Isolated";
import { NODE_TYPE_ORDER, nodeMeta } from "./labels";

export interface ActionUiState {
  busy: BusyKind | null;
  effectNote?: { en: string; ar: string } | null;
  reverted?: RevertedEffect | null;
  caveats?: string[];
  error?: ErpErrorNote | null;
  erpRefreshing: boolean;
  erpRefreshError?: ErpErrorNote | null;
}

export interface ImpactHandlers {
  onApprove: (actionId: number) => void;
  onDismiss: (actionId: number, reason: string) => void;
  onAssign: (actionId: number, impact: ImpactOut) => void;
  onConfirm: (actionId: number) => void;
  onUndo: (actionId: number) => void;
  onRefreshErp: (actionId: number) => void;
}

/** Impacted nodes grouped by node type; every node card carries its issue note and its actions. */
export function ImpactList({
  impacts, uiState, handlers,
}: {
  impacts: ImpactOut[];
  uiState: (actionId: number) => ActionUiState;
  handlers: ImpactHandlers;
}) {
  const groups = useMemo(() => {
    const byType = new Map<string, ImpactOut[]>();
    for (const impact of impacts) {
      const list = byType.get(impact.node_type) ?? [];
      list.push(impact);
      byType.set(impact.node_type, list);
    }
    const known = NODE_TYPE_ORDER.filter((t) => byType.has(t));
    const other = [...byType.keys()].filter((t) => !NODE_TYPE_ORDER.includes(t)).sort();
    return [...known, ...other].map((type) => ({ type, items: byType.get(type) ?? [] }));
  }, [impacts]);

  if (impacts.length === 0) {
    return (
      <p className="chg-empty">
        <Bi en="No organizational nodes are affected by this change." ar="لا توجد عناصر تنظيمية متأثرة بهذا التغيير." />
      </p>
    );
  }

  return (
    <div className="chg-groups">
      {groups.map(({ type, items }) => {
        const meta = nodeMeta(type);
        return (
          <section key={type} className="chg-group" aria-label={meta.many.en}>
            <h3 className="chg-group-title">
              <Icon icon={meta.icon} size={18} />
              <Bi en={meta.many.en} ar={meta.many.ar} />
              <span className="chg-group-count tabular">{items.length}</span>
            </h3>
            <ul className="chg-nodes">
              {items.map((impact) => {
                const scope = SCOPE_MATCH_LABEL[impact.scope_match];
                return (
                  <li key={impact.id} className="chg-node" id={`node-${impact.id}`}>
                    <header className="chg-node-head">
                      <span className="chg-node-icon" aria-hidden="true"><Icon icon={meta.icon} size={18} /></span>
                      <div className="chg-node-titles">
                        <h4 className="chg-node-name"><bdi>{impact.node_name}</bdi></h4>
                        <p className="chg-node-path">
                          <bdi>{impact.path_summary}</bdi>
                          {scope && <> · <Bi en={scope.en} ar={scope.ar} /></>}
                        </p>
                      </div>
                      <Badge variant="neutral"><Bi en={meta.one.en} ar={meta.one.ar} /></Badge>
                    </header>
                    <div className="chg-node-note">
                      <span className="chg-node-note-label"><Bi en="Issue" ar="المشكلة" /></span>
                      <p><Bi en={impact.note_en} ar={<Isolated text={impact.note_ar || impact.note_en} />} /></p>
                    </div>
                    {impact.actions.length > 0 && (
                      <div className="chg-node-actions">
                        {impact.actions.map((action) => {
                          const ui = uiState(action.id);
                          const props: ActionCardProps = {
                            action,
                            nodeType: impact.node_type,
                            ...ui,
                            onApprove: () => handlers.onApprove(action.id),
                            onDismiss: (reason) => handlers.onDismiss(action.id, reason),
                            onAssign: () => handlers.onAssign(action.id, impact),
                            onConfirm: () => handlers.onConfirm(action.id),
                            onUndo: () => handlers.onUndo(action.id),
                            onRefreshErp: () => handlers.onRefreshErp(action.id),
                          };
                          return <ActionCard key={action.id} {...props} />;
                        })}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
