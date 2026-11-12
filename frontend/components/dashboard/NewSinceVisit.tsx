"use client";

import { useEffect, useRef, useState } from "react";
import { Sparkles } from "lucide-react";
import { Bi } from "@/components/Bi";
import { Button, Icon } from "@/components/ui";
import { getNewCount } from "@/lib/api-visibility";
import type { NewCount } from "@/lib/types-visibility";

const LAST_SEEN_KEY = "xposure_last_seen";
/** The user has to stay this long on the page before "last seen" moves forward. */
const DWELL_MS = 6_000;

function readLastSeen(): string | null {
  try {
    return localStorage.getItem(LAST_SEEN_KEY);
  } catch {
    return null;
  }
}

function writeLastSeen(iso: string): void {
  try {
    localStorage.setItem(LAST_SEEN_KEY, iso);
  } catch {
    /* private mode or blocked storage: the chip simply will not persist */
  }
}

/**
 * "N new since your last visit" chip. The baseline is read once when the page
 * opens. localStorage moves forward only after a few seconds on the page or
 * when the user clicks "Mark seen", so a quick bounce does not swallow the
 * news. Without stored history (first visit) nothing is shown.
 */
export function NewSinceVisit() {
  const [count, setCount] = useState<NewCount | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const startedAt = useRef(new Date().toISOString());

  useEffect(() => {
    const baseline = readLastSeen();
    const controller = new AbortController();
    if (baseline) {
      getNewCount(baseline, controller.signal)
        .then(setCount)
        .catch(() => setCount(null));
    }
    const timer = window.setTimeout(() => writeLastSeen(startedAt.current), DWELL_MS);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, []);

  if (!count || count.total <= 0 || dismissed) return null;
  const critical = count.by_matrix?.critical ?? 0;

  return (
    <div className="dash-newchip" role="status">
      <Icon icon={Sparkles} size={14} />
      <span>
        <Bi
          en={`${count.total} new ${count.total === 1 ? "change" : "changes"} since your last visit${critical > 0 ? `, ${critical} critical` : ""}`}
          ar={`${count.total} ${count.total === 1 ? "تغيير جديد" : "تغييرات جديدة"} منذ زيارتك الأخيرة${critical > 0 ? `، منها ${critical} حرجة` : ""}`}
        />
      </span>
      <Button
        variant="link"
        size="sm"
        onClick={() => {
          writeLastSeen(new Date().toISOString());
          setDismissed(true);
        }}
      >
        <Bi en="Mark seen" ar="تمّت المشاهدة" />
      </Button>
    </div>
  );
}
