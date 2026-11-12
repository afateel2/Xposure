"use client";

import { useEffect, useRef, useState, type ChangeEvent, type FormEvent, type ReactNode } from "react";
import { CircleCheck } from "lucide-react";
import { Bi } from "@/components/Bi";
import { Button, Field, Icon, Input, Select, Textarea } from "@/components/ui";
import { t, useLang } from "@/lib/lang";

type Values = {
  name: string;
  organization: string;
  email: string;
  role: string;
  message: string;
};

type ValidatedField = "name" | "organization" | "email";
type ErrorKind = "required" | "format";
type Errors = Partial<Record<ValidatedField, ErrorKind>>;

const EMPTY: Values = { name: "", organization: "", email: "", role: "", message: "" };

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

const ROLES: { value: string; en: string; ar: string }[] = [
  { value: "compliance", en: "Compliance", ar: "الامتثال" },
  { value: "it-security", en: "IT security", ar: "أمن تقنية المعلومات" },
  { value: "ot-engineering", en: "OT engineering", ar: "هندسة التقنيات التشغيلية (OT)" },
  { value: "operations", en: "Operations", ar: "العمليات" },
  { value: "legal", en: "Legal", ar: "الشؤون القانونية" },
  { value: "procurement", en: "Procurement", ar: "المشتريات" },
  { value: "other", en: "Other", ar: "أخرى" },
];

function validate(values: Values): Errors {
  const errors: Errors = {};
  if (!values.name.trim()) errors.name = "required";
  if (!values.organization.trim()) errors.organization = "required";
  const email = values.email.trim();
  if (!email) errors.email = "required";
  else if (!EMAIL_PATTERN.test(email)) errors.email = "format";
  return errors;
}

function errorText(field: ValidatedField, kind: ErrorKind): ReactNode {
  if (field === "name") return <Bi en="Please enter your name." ar="الرجاء إدخال اسمك." />;
  if (field === "organization") return <Bi en="Please enter your organization." ar="الرجاء إدخال اسم مؤسستك." />;
  if (kind === "required") return <Bi en="Please enter your work email." ar="الرجاء إدخال بريدك الإلكتروني في العمل." />;
  return (
    <Bi
      en="Enter a valid email address, for example name@company.com."
      ar={<>أدخل بريدًا إلكترونيًا صحيحًا، مثل <bdi>name@company.com</bdi>.</>}
    />
  );
}

function Required() {
  return (
    <span className="site-req" aria-hidden="true">
      *
    </span>
  );
}

/**
 * Request-a-demo form of the public landing page. It is a prototype: it
 * validates on the client and then shows a confirmation panel. It deliberately
 * sends nothing anywhere (no fetch, no storage).
 */
export function DemoRequestForm({ labelledBy = "demo-title" }: { labelledBy?: string }) {
  const lang = useLang();
  const [values, setValues] = useState<Values>(EMPTY);
  const [errors, setErrors] = useState<Errors>({});
  const [submittedName, setSubmittedName] = useState<string | null>(null);
  const [focusTick, setFocusTick] = useState(0);
  const formRef = useRef<HTMLFormElement>(null);
  const thanksRef = useRef<HTMLDivElement>(null);

  // After a failed submit, move focus to the first invalid field.
  useEffect(() => {
    if (focusTick === 0) return;
    formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }, [focusTick]);

  // After a successful submit, move focus to the confirmation panel.
  useEffect(() => {
    if (submittedName !== null) thanksRef.current?.focus();
  }, [submittedName]);

  function onChange(key: keyof Values) {
    return (e: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
      const value = e.target.value;
      setValues((prev) => ({ ...prev, [key]: value }));
      if (key === "name" || key === "organization" || key === "email") {
        setErrors((prev) => {
          if (!prev[key]) return prev;
          const next = { ...prev };
          delete next[key];
          return next;
        });
      }
    };
  }

  function onEmailBlur() {
    const email = values.email.trim();
    if (email && !EMAIL_PATTERN.test(email)) setErrors((prev) => ({ ...prev, email: "format" }));
  }

  function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const next = validate(values);
    setErrors(next);
    if (Object.keys(next).length > 0) {
      setFocusTick((n) => n + 1);
      return;
    }
    // Prototype: nothing is sent anywhere. Only the name is kept, in memory,
    // to personalise the confirmation panel.
    setSubmittedName(values.name.trim());
  }

  if (submittedName !== null) {
    return (
      <div className="site-thanks" ref={thanksRef} tabIndex={-1} role="status">
        <span className="site-thanks-icon">
          <Icon icon={CircleCheck} size={26} />
        </span>
        <h3>
          <Bi en={<>Thank you, <bdi>{submittedName}</bdi>.</>} ar={<>شكرًا لك، <bdi>{submittedName}</bdi>.</>} />
        </h3>
        <p>
          <Bi
            en="This form is a prototype: nothing was sent. To see Xposure now, open the live demo."
            ar={<>هذا النموذج تجريبي ولم يُرسل أي شيء. لمشاهدة <bdi>Xposure</bdi> الآن، افتح العرض المباشر.</>}
          />
        </p>
        <Button href="/" variant="primary" size="lg">
          <Bi en="Open the live demo" ar="افتح العرض المباشر" />
        </Button>
      </div>
    );
  }

  return (
    <form ref={formRef} onSubmit={onSubmit} noValidate aria-labelledby={labelledBy}>
      <div className="site-form-grid">
        <Field
          label={<><Bi en="Name" ar="الاسم" /><Required /></>}
          htmlFor="demo-name"
          error={errors.name ? errorText("name", errors.name) : null}
        >
          <Input
            id="demo-name"
            name="name"
            autoComplete="name"
            maxLength={120}
            value={values.name}
            onChange={onChange("name")}
            invalid={!!errors.name}
            aria-required="true"
            placeholder={t(lang, "Your full name", "اسمك الكامل")}
          />
        </Field>

        <Field
          label={<><Bi en="Organization" ar="المؤسسة" /><Required /></>}
          htmlFor="demo-organization"
          error={errors.organization ? errorText("organization", errors.organization) : null}
        >
          <Input
            id="demo-organization"
            name="organization"
            autoComplete="organization"
            maxLength={160}
            value={values.organization}
            onChange={onChange("organization")}
            invalid={!!errors.organization}
            aria-required="true"
            placeholder={t(lang, "Your organization", "اسم مؤسستك")}
          />
        </Field>

        <Field
          label={<><Bi en="Work email" ar="البريد الإلكتروني في العمل" /><Required /></>}
          htmlFor="demo-email"
          error={errors.email ? errorText("email", errors.email) : null}
        >
          <Input
            id="demo-email"
            name="email"
            type="email"
            dir="ltr"
            autoComplete="email"
            maxLength={200}
            value={values.email}
            onChange={onChange("email")}
            onBlur={onEmailBlur}
            invalid={!!errors.email}
            aria-required="true"
            placeholder="name@company.com"
          />
        </Field>

        <Field label={<Bi en="Role" ar="الدور الوظيفي" />} htmlFor="demo-role">
          <Select id="demo-role" name="role" value={values.role} onChange={onChange("role")}>
            <option value="">{t(lang, "Select your role", "اختر دورك الوظيفي")}</option>
            {ROLES.map((role) => (
              <option key={role.value} value={role.value}>
                {t(lang, role.en, role.ar)}
              </option>
            ))}
          </Select>
        </Field>

        <Field
          className="site-field-wide"
          label={<Bi en="Message (optional)" ar="الرسالة (اختياري)" />}
          htmlFor="demo-message"
        >
          <Textarea
            id="demo-message"
            name="message"
            rows={4}
            maxLength={2000}
            value={values.message}
            onChange={onChange("message")}
            placeholder={t(lang, "Anything you would like us to know", "أي شيء تودّ أن نعرفه")}
          />
        </Field>
      </div>

      <div className="site-form-foot">
        <Button type="submit" variant="primary" size="lg">
          <Bi en="Request a demo" ar="اطلب عرضًا توضيحيًا" />
        </Button>
        <p className="site-form-hint">
          <Bi en="Fields marked * are required." ar="الحقول المعلَّمة بعلامة * مطلوبة." />
        </p>
      </div>
    </form>
  );
}
