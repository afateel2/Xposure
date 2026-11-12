"use client";

import { Suspense, useEffect, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Bi } from "@/components/Bi";
import { Button, Card, Field, Icon, Input, useToast } from "@/components/ui";
import { LogIn } from "lucide-react";
import { login, setSessionResult, useSession } from "@/lib/auth";
import { useLang } from "@/lib/lang";

/** The six named reviewers (backend/scripts/seed_users.py), for the quick-
 * pick list. Clicking one only fills the email field, never the password
 * (demo convenience, not a login shortcut) — see that script's own
 * docstring for why every seeded user currently shares one password. */
const PEOPLE = [
  { email: "compliance@eastern-industrial.example", name_en: "Reem Al-Mutairi", name_ar: "ريم المطيري", title_en: "Compliance Officer", title_ar: "مسؤولة الامتثال" },
  { email: "it.security@eastern-industrial.example", name_en: "Khalid Al-Harbi", name_ar: "خالد الحربي", title_en: "IT Security Lead", title_ar: "رئيس أمن تقنية المعلومات" },
  { email: "ot.engineering@eastern-industrial.example", name_en: "Faisal Al-Qahtani", name_ar: "فيصل القحطاني", title_en: "OT Engineering Lead", title_ar: "رئيس هندسة أنظمة التحكم الصناعي" },
  { email: "operations@eastern-industrial.example", name_en: "Nasser Al-Dossari", name_ar: "ناصر الدوسري", title_en: "Operations Manager", title_ar: "مدير العمليات" },
  { email: "legal@eastern-industrial.example", name_en: "Abdullah Al-Otaibi", name_ar: "عبدالله العتيبي", title_en: "Legal Counsel", title_ar: "المستشار القانوني" },
  { email: "procurement@eastern-industrial.example", name_en: "Huda Al-Zahrani", name_ar: "هدى الزهراني", title_en: "Procurement Lead", title_ar: "رئيسة المشتريات" },
];

function LoginForm() {
  const lang = useLang();
  const router = useRouter();
  const params = useSearchParams();
  const toast = useToast();
  const session = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const next = params.get("next") || "/";

  useEffect(() => {
    if (session.authenticated) router.replace(next);
  }, [session.authenticated, next, router]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const result = await login(email.trim(), password);
      setSessionResult(result);
      toast.success(<Bi en={`Signed in as ${result.user?.name_en}.`} ar={`تم تسجيل الدخول باسم ${result.user?.name_ar}.`} />);
      router.replace(next);
    } catch (err) {
      toast.error(<Bi en={String((err as Error).message)} ar={String((err as Error).message)} />);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-page">
      <Card className="login-card" title={<Bi en="Sign in" ar="تسجيل الدخول" />}>
        <p className="xp-muted">
          <Bi
            en="Sign in to approve, delegate, undo, or run a scan. Dashboards and reports stay open without signing in."
            ar="سجّل الدخول لاعتماد الإجراءات أو إسنادها أو التراجع عنها أو تشغيل فحص. لوحات التحكم والتقارير تبقى متاحة دون تسجيل دخول."
          />
        </p>

        <form onSubmit={onSubmit} className="stack login-form">
          <Field label={<Bi en="Email" ar="البريد الإلكتروني" />}>
            <Input
              type="email"
              required
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@eastern-industrial.example"
            />
          </Field>
          <Field label={<Bi en="Password" ar="كلمة المرور" />}>
            <Input
              id="login-password"
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <Button type="submit" variant="primary" loading={busy} icon={<Icon icon={LogIn} size={16} />}>
            <Bi en="Sign in" ar="تسجيل الدخول" />
          </Button>
        </form>

        <div className="login-people">
          <p className="xp-muted login-people-label"><Bi en="Quick pick (fills email only)" ar="اختيار سريع (يملأ البريد الإلكتروني فقط)" /></p>
          <div className="login-people-grid">
            {PEOPLE.map((p) => (
              <button
                key={p.email}
                type="button"
                className="login-person"
                onClick={() => {
                  setEmail(p.email);
                  document.getElementById("login-password")?.focus();
                }}
              >
                <span className="login-person-name">{lang === "ar" ? p.name_ar : p.name_en}</span>
                <span className="login-person-title xp-muted">{lang === "ar" ? p.title_ar : p.title_en}</span>
              </button>
            ))}
          </div>
        </div>
      </Card>
    </main>
  );
}

/** useSearchParams() needs a Suspense boundary or the page cannot be prerendered in a production build. */
export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
