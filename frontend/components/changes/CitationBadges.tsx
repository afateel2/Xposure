"use client";

import { CircleAlert, CircleCheck, CircleX, Info, TriangleAlert } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Bi } from "@/components/Bi";
import { Badge, Icon, type BadgeVariant } from "@/components/ui";
import { t, useLang } from "@/lib/lang";
import type { ChangeDetailOut, CitationCheckOut } from "@/lib/types";

/**
 * "Is the clause text we show really in the stored source file?" Answered by
 * plain code (backend/app/citation.py), per side of the change. Each badge
 * says what was found and where, and a failed check says so plainly: it is a
 * prompt to read the original, never hidden.
 */
export function CitationBadges({ detail }: { detail: ChangeDetailOut }) {
  const lang = useLang();
  const citation = detail.citation;
  if (!citation || (!citation.old && !citation.new)) return null;

  const rows: { key: string; label: string; check: CitationCheckOut }[] = [];
  if (citation.old) rows.push({ key: "old", label: detail.old_version_label ?? t(lang, "Previous", "السابق"), check: citation.old });
  if (citation.new) rows.push({ key: "new", label: detail.new_version_label ?? t(lang, "New", "الجديد"), check: citation.new });

  return (
    <div
      className="chg-cites"
      role="group"
      aria-label={t(lang, "Citation check against the source files", "فحص الاستشهاد مقابل ملفات المصدر")}
    >
      <span className="chg-cites-title">
        <Bi en="Citation check" ar="فحص الاستشهاد" />
        <span
          className="chg-cites-help"
          tabIndex={0}
          title={t(
            lang,
            "Plain code opens the stored source PDF, confirms it still has the hash recorded at ingestion, and looks for this clause's words, in order, on the cited page. Case, spacing and punctuation are ignored. No model is involved.",
            "يفتح الكود ملف المصدر المحفوظ، ويتأكد أن بصمته ما زالت كما سُجّلت عند الاستيعاب، ثم يبحث عن كلمات البند بالترتيب في الصفحة المُستشهَد بها دون اعتبار لحالة الأحرف أو المسافات أو علامات الترقيم. لا يتدخل أي نموذج."
          )}
        >
          <Icon icon={Info} size={14} />
        </span>
      </span>
      {rows.map(({ key, label, check }) => (
        <CitationBadge key={key} label={label} check={check} />
      ))}
    </div>
  );
}

function CitationBadge({ label, check }: { label: string; check: CitationCheckOut }) {
  const { variant, icon, text } = describe(check);
  return (
    <Badge variant={variant} className="chg-cite">
      <Icon icon={icon} size={14} />
      <b><bdi>{label}</bdi></b>
      <span>{text}</span>
    </Badge>
  );
}

function describe(check: CitationCheckOut): { variant: BadgeVariant; icon: LucideIcon; text: React.ReactNode } {
  switch (check.status) {
    case "verified":
      return {
        variant: "success",
        icon: CircleCheck,
        text: <Bi en={<>Verified in the source file, page <span className="tabular">{check.page}</span></>} ar={<>تم التحقق في ملف المصدر، الصفحة <span className="tabular">{check.page}</span></>} />,
      };
    case "other_page":
      return {
        variant: "warning",
        icon: TriangleAlert,
        text: (
          <Bi
            en={<>Found on page <span className="tabular">{check.page}</span>, not the cited page <span className="tabular">{check.cited_page ?? "?"}</span></>}
            ar={<>وُجد في الصفحة <span className="tabular">{check.page}</span> لا في الصفحة المُستشهَد بها <span className="tabular">{check.cited_page ?? "؟"}</span></>}
          />
        ),
      };
    case "not_found":
      return {
        variant: "danger",
        icon: CircleX,
        text: (
          <Bi
            en="Not found as written in the source file. Read the original before relying on this text."
            ar="لم يُعثر على النص كما هو مكتوب في ملف المصدر. اقرأ الأصل قبل الاعتماد على هذا النص."
          />
        ),
      };
    case "file_changed":
      return {
        variant: "danger",
        icon: CircleAlert,
        text: (
          <Bi
            en="The source file no longer matches the hash recorded at ingestion."
            ar="ملف المصدر لم يعد مطابقًا للبصمة المسجَّلة عند الاستيعاب."
          />
        ),
      };
    default:
      return {
        variant: "neutral",
        icon: Info,
        text: <Bi en="Source file not available to check" ar="ملف المصدر غير متاح للفحص" />,
      };
  }
}
