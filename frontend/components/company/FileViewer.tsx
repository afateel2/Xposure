"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Bi } from "@/components/Bi";
import { RelTime } from "@/components/RelTime";
import { Badge, BrandMotif, Button, Card, FileText, History, Icon, Modal, Segmented, Undo2, useToast } from "@/components/ui";
import { getCompanyFile, revertCompanyFile } from "@/lib/api-company";
import { ApiError, errorText } from "@/lib/api-http";
import type { FileDetail, FileVersion } from "@/lib/types-company";
import { DiffView } from "./DiffView";
import { MiniMarkdown } from "./MiniMarkdown";
import { AgentChip, KIND_LABEL, ORIGIN_LABEL, ORIGIN_WHO, fmtSize } from "./labels";

type Tab = "document" | "changes";

const vLabel = (v: FileVersion) => (v.doc_version ? `v${v.doc_version}` : `#${v.n}`);

/**
 * File viewer: header with the revert action, the version history, and two
 * views of the selected version: the document itself and the changes since the
 * version before it (unified diff from the backend, with line numbers).
 */
export function FileViewer({
  path, refreshKey, onChanged,
}: {
  path: string;
  /** Changes when the file was modified elsewhere (new version), so the viewer reloads. */
  refreshKey: string;
  onChanged: () => void;
}) {
  const toast = useToast();
  const [latest, setLatest] = useState<FileDetail | null>(null);
  const [view, setView] = useState<FileDetail | null>(null);
  const [selectedN, setSelectedN] = useState<number | null>(null);
  const [tab, setTab] = useState<Tab>("document");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [reverting, setReverting] = useState(false);
  const lastPath = useRef<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const d = await getCompanyFile(path, undefined, signal);
      setLatest(d);
      setError(null);
      if (lastPath.current !== path) {
        lastPath.current = path;
        setSelectedN(null);
        setView(null);
        const last = d.versions[d.versions.length - 1];
        setTab(d.diff && last?.origin === "agent" ? "changes" : "document");
      } else {
        // Same file, new version arrived: show it.
        setSelectedN(null);
        setView(null);
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    void load(ctrl.signal);
    return () => ctrl.abort();
  }, [load, refreshKey]);

  // Fetch an older version when one is picked.
  useEffect(() => {
    if (selectedN == null || !latest || selectedN === latest.content_version_n) {
      setView(null);
      return;
    }
    const ctrl = new AbortController();
    getCompanyFile(path, selectedN, ctrl.signal)
      .then((d) => {
        setView(d);
        if (!d.diff) setTab("document");
      })
      .catch((err) => {
        if (!(err instanceof DOMException && err.name === "AbortError")) setError(errorText(err));
      });
    return () => ctrl.abort();
  }, [selectedN, latest, path]);

  async function revert() {
    if (!latest) return;
    setReverting(true);
    try {
      const d = await revertCompanyFile(path);
      const prev = d.versions.find((v) => v.n === d.reverted_to_n);
      setLatest(d);
      setSelectedN(null);
      setView(null);
      setTab("document");
      setConfirmOpen(false);
      toast.success(
        <Bi
          en={<>Restored version {prev?.doc_version ?? d.reverted_to_n} of <bdi>{d.name}</bdi> as a new version. History is kept.</>}
          ar={<>استُعيد الإصدار {prev?.doc_version ?? d.reverted_to_n} من <bdi>{d.name}</bdi> كإصدار جديد، والسجل محفوظ.</>}
        />,
      );
      onChanged();
    } catch (err) {
      const msg = errorText(err);
      toast.error(
        <Bi en={<>Could not restore the version: {msg}</>} ar={<>تعذّرت استعادة الإصدار: <bdi dir="auto">{msg}</bdi></>} />,
      );
      if (err instanceof ApiError && err.status === 409) setConfirmOpen(false);
    } finally {
      setReverting(false);
    }
  }

  if (loading && !latest) {
    return (
      <Card className="fac-viewer" title={<Bi en="Document" ar="الوثيقة" />} icon={<Icon icon={FileText} size={18} />}>
        <BrandMotif variant="spinner" title={<Bi en="Loading the document" ar="جارٍ تحميل الوثيقة" />} />
      </Card>
    );
  }
  if (error && !latest) {
    return (
      <div className="xp-card xp-error-card fac-viewer" role="alert">
        <b><Bi en="The document could not be loaded" ar="تعذّر تحميل الوثيقة" /></b>
        <p className="xp-muted"><bdi dir="auto">{error}</bdi></p>
        <Button variant="secondary" size="sm" onClick={() => { setLoading(true); void load(); }}><Bi en="Retry" ar="إعادة المحاولة" /></Button>
      </div>
    );
  }
  if (!latest) return null;

  const shown = view ?? latest;
  const versionsNewestFirst = [...latest.versions].reverse();
  const shownVersion = latest.versions.find((v) => v.n === shown.content_version_n);
  const isLatest = shown.content_version_n === latest.content_version_n;
  const prev = latest.versions.length >= 2 ? latest.versions[latest.versions.length - 2] : null;
  const isYaml = latest.name.toLowerCase().endsWith(".yaml");
  const diff = shown.diff;

  return (
    <Card
      className="fac-viewer"
      title={<span className="fac-viewer-title"><bdi>{latest.name}</bdi></span>}
      icon={<Icon icon={FileText} size={18} />}
      actions={
        prev ? (
          <Button variant="secondary" size="sm" icon={<Icon icon={Undo2} size={15} />} onClick={() => setConfirmOpen(true)}>
            <Bi en={<>Revert to version <bdi>{prev.doc_version ?? `#${prev.n}`}</bdi></>} ar={<>العودة إلى الإصدار <bdi>{prev.doc_version ?? `#${prev.n}`}</bdi></>} />
          </Button>
        ) : null
      }
    >
      <div className="fac-viewer-meta">
        <Badge variant="neutral"><Bi en={KIND_LABEL[latest.kind].en} ar={KIND_LABEL[latest.kind].ar} /></Badge>
        <span className="fac-file-ver tabular" dir="ltr">v{latest.version ?? "?"}</span>
        {latest.agent_edited && <AgentChip />}
        <span className="fac-viewer-path"><bdi>{latest.path}</bdi></span>
        <span className="tabular" dir="ltr">{fmtSize(latest.size)}</span>
      </div>
      {latest.nodes.length > 0 && (
        <p className="fac-viewer-used">
          <span className="xp-muted"><Bi en="Used by" ar="مرتبطة بـ" /></span>{" "}
          {latest.nodes.map((n, i) => (
            <span key={n.id}>{i > 0 ? ", " : ""}<bdi>{n.name}</bdi></span>
          ))}
        </p>
      )}

      <div className="fac-history">
        <h4 className="fac-h">
          <Icon icon={History} size={15} />
          <Bi en="Version history" ar="سجل الإصدارات" />
        </h4>
        <ol className="fac-versions">
          {versionsNewestFirst.map((v) => {
            const active = v.n === shown.content_version_n;
            const isCurrent = v.n === latest.content_version_n;
            return (
              <li key={v.n}>
                <button type="button" className={`fac-ver${active ? " is-selected" : ""}`} aria-current={active ? "true" : undefined} onClick={() => setSelectedN(v.n === latest.content_version_n ? null : v.n)}>
                  <span className="fac-ver-id tabular" dir="ltr">{vLabel(v)}<small>#{v.n}</small></span>
                  <span className="fac-ver-main">
                    <span className="fac-ver-line">
                      <Badge variant={v.origin === "agent" ? "approved" : v.origin === "revert" ? "pending" : "neutral"}>
                        <Bi en={ORIGIN_LABEL[v.origin].en} ar={ORIGIN_LABEL[v.origin].ar} />
                      </Badge>
                      {isCurrent && <span className="fac-current"><Bi en="Current" ar="الحالي" /></span>}
                    </span>
                    <span className="fac-ver-sub">
                      <span><Bi en="By" ar="بواسطة" /> <Bi en={ORIGIN_WHO[v.origin].en} ar={ORIGIN_WHO[v.origin].ar} /></span>
                      <RelTime iso={v.timestamp} />
                      {v.action_id != null && <span><Bi en="Action" ar="الإجراء" /> <bdi className="tabular">#{v.action_id}</bdi></span>}
                    </span>
                    {v.note && <span className="fac-ver-note" dir="auto">{v.note}</span>}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </div>

      {!isLatest && shownVersion && (
        <div className="fac-old-note" role="status">
          <Bi
            en={<>You are viewing <bdi>{vLabel(shownVersion)}</bdi> (#{shownVersion.n}), not the current version.</>}
            ar={<>تعرض الآن الإصدار <bdi>{vLabel(shownVersion)}</bdi> (#{shownVersion.n})، وليس الإصدار الحالي.</>}
          />
          <Button variant="link" size="sm" onClick={() => setSelectedN(null)}><Bi en="Back to current" ar="العودة إلى الحالي" /></Button>
        </div>
      )}

      <div className="fac-tabs">
        <Segmented<Tab>
          value={tab}
          onChange={setTab}
          ariaLabel="View"
          options={[
            { value: "document", label: <Bi en="Document" ar="الوثيقة" /> },
            {
              value: "changes",
              label: (
                <span className="fac-tab-changes">
                  <Bi en="Changes" ar="التغييرات" />
                  {diff && <span className="fac-tab-counts tabular" dir="ltr"><span className="fac-stat-add">+{diff.added}</span> <span className="fac-stat-del">&minus;{diff.removed}</span></span>}
                </span>
              ),
            },
          ]}
        />
        {diff && tab === "changes" && (
          <span className="fac-diff-caption">
            <Bi
              en={<>Changes in <bdi>{diff.to_version ? `v${diff.to_version}` : `#${diff.to_n}`}</bdi> compared with <bdi>{diff.from_version ? `v${diff.from_version}` : `#${diff.from_n}`}</bdi></>}
              ar={<>تغييرات <bdi>{diff.to_version ? `v${diff.to_version}` : `#${diff.to_n}`}</bdi> مقارنةً بـ <bdi>{diff.from_version ? `v${diff.from_version}` : `#${diff.from_n}`}</bdi></>}
            />
          </span>
        )}
      </div>

      {tab === "changes" ? (
        diff ? (
          <DiffView unified={diff.unified} added={diff.added} removed={diff.removed} />
        ) : (
          <p className="fac-empty-note"><Bi en="This is the first version, so there is nothing to compare it with." ar="هذا هو الإصدار الأول، فلا يوجد ما تُقارَن به." /></p>
        )
      ) : (
        <div className="fac-doc">
          {isYaml ? <pre className="fac-code" dir="ltr">{shown.content}</pre> : <MiniMarkdown source={shown.content} />}
        </div>
      )}

      <Modal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title={<Bi en="Restore the previous version?" ar="استعادة الإصدار السابق؟" />}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmOpen(false)}><Bi en="Cancel" ar="إلغاء" /></Button>
            <Button variant="danger" loading={reverting} onClick={revert}>
              <Bi en="Revert" ar="استعادة" />
            </Button>
          </>
        }
      >
        <Bi
          en={<>The content of <bdi>{prev ? vLabel(prev) : ""}</bdi> becomes the current version of <bdi>{latest.name}</bdi> as a new version. Nothing is deleted: the history keeps every version, and any agent edit it replaces is recorded as undone.</>}
          ar={<>سيصبح محتوى الإصدار <bdi>{prev ? vLabel(prev) : ""}</bdi> هو الإصدار الحالي من <bdi>{latest.name}</bdi> كإصدار جديد. لا يُحذف شيء، فالسجل يحفظ كل الإصدارات، وأي تعديل للوكيل يحلّ محله يُسجَّل على أنه مُتراجَع عنه.</>}
        />
      </Modal>
    </Card>
  );
}
