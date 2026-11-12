"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Bi } from "@/components/Bi";
import { CompanyHeader } from "@/components/company/CompanyHeader";
import { FileBrowser } from "@/components/company/FileBrowser";
import { FileViewer } from "@/components/company/FileViewer";
import { NodesTable } from "@/components/company/NodesTable";
import { BrandMotif, Button, Card, Icon, PageHeader, RefreshCw, TriangleAlert } from "@/components/ui";
import { getCompany, getCompanyFiles, getCompanyNodes } from "@/lib/api-company";
import { ApiError } from "@/lib/api-http";
import { usePoll } from "@/lib/use-poll";

export default function CompanyPage() {
  const company = usePoll(getCompany, 15000);
  const nodes = usePoll(getCompanyNodes, 15000);
  const files = usePoll(getCompanyFiles, 10000);
  const [selected, setSelected] = useState<string | null>(null);
  const viewerRef = useRef<HTMLDivElement>(null);

  const list = files.data?.files ?? null;

  // First selection: ?file= from a link, else the file the agent edited most recently, else the first file.
  useEffect(() => {
    if (selected || !list || list.length === 0) return;
    let wanted: string | null = null;
    try {
      wanted = new URLSearchParams(window.location.search).get("file");
    } catch {
      wanted = null;
    }
    const byParam = wanted ? list.find((f) => f.path === wanted) : undefined;
    const edited = [...list].filter((f) => f.agent_edited).sort((a, b) => b.last_modified.localeCompare(a.last_modified))[0];
    setSelected((byParam ?? edited ?? list[0]).path);
  }, [list, selected]);

  const select = useCallback((path: string) => {
    setSelected(path);
    try {
      window.history.replaceState(null, "", `?file=${encodeURIComponent(path)}`);
    } catch {
      // history unavailable: selection still works
    }
    if (window.matchMedia("(max-width: 1100px)").matches) {
      window.setTimeout(() => viewerRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    }
  }, []);

  const changed = useCallback(() => {
    files.reload();
    nodes.reload();
    company.reload();
  }, [files, nodes, company]);

  const selectedFile = list?.find((f) => f.path === selected) ?? null;
  const refreshKey = selectedFile ? `${selectedFile.version_count}:${selectedFile.last_modified}` : "";

  const unavailable = company.error instanceof ApiError && company.error.unavailable && !company.data;

  return (
    <main>
      <PageHeader
        title={<Bi en="Facility profile" ar="ملف المنشأة" />}
        subtitle={<Bi en="Who the company is, which documents the agent works on, and what changed in each one." ar="من هي الشركة، وما الوثائق التي يعمل عليها الوكيل، وما الذي تغيّر في كل منها." />}
      />

      {company.loading && !company.data ? (
        <Card><BrandMotif variant="spinner" title={<Bi en="Loading the facility profile" ar="جارٍ تحميل ملف المنشأة" />} /></Card>
      ) : unavailable || (!company.data && company.error) ? (
        <div className="xp-card xp-error-card fac-unavailable" role="alert">
          <Icon icon={TriangleAlert} size={20} />
          <div className="fac-unavailable-text">
            <b><Bi en="The facility profile is not available" ar="ملف المنشأة غير متاح" /></b>
            <span>
              <Bi
                en="The backend did not answer the company routes. Restart it with the latest code and retry."
                ar="لم يستجب الخادم لمسارات الشركة. أعد تشغيله بأحدث إصدار ثم أعد المحاولة."
              />
            </span>
          </div>
          <Button variant="secondary" size="sm" icon={<Icon icon={RefreshCw} size={14} />} onClick={changed}><Bi en="Retry" ar="إعادة المحاولة" /></Button>
        </div>
      ) : company.data ? (
        <CompanyHeader company={company.data} nodes={nodes.data} />
      ) : null}

      <div className="fac-docs">
        <FileBrowser files={list} selected={selected} onSelect={select} loading={files.loading} error={files.error != null} />
        <div ref={viewerRef} className="fac-viewer-slot">
          {selected ? (
            <FileViewer path={selected} refreshKey={refreshKey} onChanged={changed} />
          ) : (
            <Card><BrandMotif variant="empty" title={<Bi en="Select a document" ar="اختر وثيقة" />} hint={<Bi en="Its content, version history and changes appear here." ar="يظهر هنا محتواها وسجل إصداراتها وتغييراتها." />} /></Card>
          )}
        </div>
      </div>

      <NodesTable nodes={nodes.data?.nodes ?? null} loading={nodes.loading} error={nodes.error != null} onOpenFile={select} />
    </main>
  );
}
