"use client";

import { useState } from "react";
import { Bi } from "@/components/Bi";
import { Button, Card, FlaskConical, Icon, Modal } from "@/components/ui";
import { RotateCcw } from "lucide-react";
import type { DemoStatus } from "@/lib/types-demo";

/**
 * "Demo controls": visible only when the backend says demo_mode is true.
 * Reset asks for confirmation first: it restores the company files and
 * clears detected changes, and keeps the audit log.
 */
export function DemoControls({
  status, running, onReset, resetting,
}: {
  status: DemoStatus | null;
  running: boolean;
  onReset: () => Promise<boolean>;
  resetting: boolean;
}) {
  const [open, setOpen] = useState(false);
  if (!status || !status.demo_mode) return null;
  const blocked = running || status.can_reset === false;

  return (
    <Card title={<Bi en="Demo controls" ar="أدوات العرض" />} icon={<Icon icon={FlaskConical} size={18} />} className="run-demo">
      {status.needs_reset && (
        <p className="run-demo-warn" role="status">
          <Bi
            en="The last run did not finish cleanly. Reset the demo, then scan again."
            ar="لم يكتمل التشغيل الأخير بصورة سليمة. أعد ضبط العرض ثم أعد الفحص."
          />
        </p>
      )}
      <p className="run-demo-text">
        <Bi
          en="Return the whole demo to its starting point to record it again. This is a demo tool and is not part of the product."
          ar="أعد العرض كاملًا إلى نقطة البداية لتسجيله من جديد. هذه أداة للعرض التجريبي وليست جزءًا من المنتج."
        />
      </p>
      <Button variant="secondary" icon={<Icon icon={RotateCcw} size={16} />} disabled={blocked} onClick={() => setOpen(true)}>
        <Bi en="Reset demo" ar="إعادة ضبط العرض" />
      </Button>
      {blocked && running && (
        <p className="run-demo-hint"><Bi en="Available when the running scan ends." ar="متاح عند انتهاء الفحص الجاري." /></p>
      )}
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={<Bi en="Reset the demo?" ar="إعادة ضبط العرض؟" />}
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)}><Bi en="Cancel" ar="إلغاء" /></Button>
            <Button
              variant="danger"
              loading={resetting}
              onClick={async () => {
                const ok = await onReset();
                if (ok) setOpen(false);
              }}
            >
              <Bi en="Reset demo" ar="إعادة ضبط العرض" />
            </Button>
          </>
        }
      >
        <Bi
          en={<>Return the company to <bdi>ECC-1:2018</bdi> baseline? Company files are restored and detected changes are cleared. The audit log is kept.</>}
          ar={<>هل تريد إعادة الشركة إلى الوضع المرجعي <bdi>ECC-1:2018</bdi>؟ ستُستعاد ملفات الشركة وتُمسح التغييرات المكتشفة، ويبقى سجل التدقيق محفوظًا.</>}
        />
      </Modal>
    </Card>
  );
}
