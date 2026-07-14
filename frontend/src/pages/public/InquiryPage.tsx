import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { z } from "zod";
import {
  TextField,
  TextArea,
  Label,
  Input,
  Description,
  FieldError,
  Checkbox,
  Switch,
  Button,
  Alert,
  Spinner,
} from "@heroui/react";
import { useTranslation } from "react-i18next";
import { useSubmitInquiry, useTours } from "@/lib/queries";
import { useLang } from "@/lib/nav";
import { tt } from "@/i18n";
import { Container, Section, SectionHeading } from "@/components/primitives";
import { Seo } from "@/components/site/Seo";

const schema = z.object({
  fullName: z.string().min(2, "Please enter your name"),
  email: z.string().email("Enter a valid email"),
  phone: z.string().optional(),
  country: z.string().optional(),
  arrivalDate: z.string().optional(),
  departureDate: z.string().optional(),
  groupSize: z.string().optional(),
  message: z.string().min(10, "Tell Georgie a little about your trip"),
  consent: z.literal(true, { errorMap: () => ({ message: "Consent is required" }) }),
});

type Errors = Partial<Record<string, string>>;

export function Component() {
  const { t } = useTranslation();
  const lang = useLang();
  const [params] = useSearchParams();
  const preTour = params.get("tour") ?? "";
  const { data: toursData } = useTours({ pageSize: 50 });
  const submit = useSubmitInquiry();

  const [form, setForm] = useState({
    fullName: "",
    email: "",
    phone: "",
    country: "",
    arrivalDate: "",
    departureDate: "",
    flexibleDates: false,
    groupSize: "",
    children: "",
    selectedTourSlug: preTour,
    activityLevel: "",
    needTransport: false,
    message: "",
    consent: false,
    marketingOptIn: false,
  });
  const [errors, setErrors] = useState<Errors>({});

  const set = (k: string, v: unknown) => setForm((f) => ({ ...f, [k]: v }));

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const parsed = schema.safeParse(form);
    if (!parsed.success) {
      const errs: Errors = {};
      parsed.error.issues.forEach((i) => (errs[String(i.path[0])] = i.message));
      setErrors(errs);
      return;
    }
    setErrors({});
    submit.mutate({
      ...form,
      groupSize: form.groupSize ? Number(form.groupSize) : undefined,
      children: form.children ? Number(form.children) : undefined,
    });
  };

  if (submit.isSuccess) {
    return (
      <Section>
        <Container size="narrow">
          <Alert>
            <Alert.Indicator />
            <Alert.Content>
              <Alert.Title>{t("inquiry.success")}</Alert.Title>
            </Alert.Content>
          </Alert>
        </Container>
      </Section>
    );
  }

  return (
    <>
      <Seo title={`${t("actions.sendInquiry")} — Svaneti with Georgie`} description={t("home.inquiryBody")} canonicalPath={`/${lang}/inquiry`} />
      <Section>
        <Container size="narrow">
          <SectionHeading as="h1" eyebrow={t("nav.contact")} title={t("home.inquiryTitle")} intro={t("home.inquiryBody")} />

          {submit.isError && (
            <Alert className="mb-6 border-danger/40">
              <Alert.Indicator />
              <Alert.Content>
                <Alert.Title>{t("inquiry.error")}</Alert.Title>
              </Alert.Content>
            </Alert>
          )}

          <form onSubmit={onSubmit} className="grid gap-5 sm:grid-cols-2" noValidate>
            <TextField isInvalid={!!errors.fullName} isRequired className="sm:col-span-1">
              <Label>{t("inquiry.fullName")}</Label>
              <Input value={form.fullName} onChange={(e) => set("fullName", e.target.value)} autoComplete="name" />
              {errors.fullName && <FieldError>{errors.fullName}</FieldError>}
            </TextField>

            <TextField isInvalid={!!errors.email} isRequired>
              <Label>{t("inquiry.email")}</Label>
              <Input type="email" value={form.email} onChange={(e) => set("email", e.target.value)} autoComplete="email" />
              {errors.email && <FieldError>{errors.email}</FieldError>}
            </TextField>

            <TextField>
              <Label>{t("inquiry.phone")}</Label>
              <Input value={form.phone} onChange={(e) => set("phone", e.target.value)} inputMode="tel" />
            </TextField>

            <TextField>
              <Label>{t("inquiry.country")}</Label>
              <Input value={form.country} onChange={(e) => set("country", e.target.value)} autoComplete="country-name" />
            </TextField>

            <TextField>
              <Label>{t("inquiry.arrival")}</Label>
              <Input type="date" value={form.arrivalDate} onChange={(e) => set("arrivalDate", e.target.value)} />
            </TextField>

            <TextField>
              <Label>{t("inquiry.departure")}</Label>
              <Input type="date" value={form.departureDate} onChange={(e) => set("departureDate", e.target.value)} />
            </TextField>

            <TextField>
              <Label>{t("inquiry.groupSize")}</Label>
              <Input type="number" min={1} value={form.groupSize} onChange={(e) => set("groupSize", e.target.value)} />
            </TextField>

            <TextField>
              <Label>{t("inquiry.children")}</Label>
              <Input type="number" min={0} value={form.children} onChange={(e) => set("children", e.target.value)} />
            </TextField>

            <div className="sm:col-span-2">
              <label htmlFor="tour" className="mb-1.5 block text-sm font-medium">{t("inquiry.selectedTour")}</label>
              <select
                id="tour"
                value={form.selectedTourSlug}
                onChange={(e) => set("selectedTourSlug", e.target.value)}
                className="w-full rounded-lg border border-border bg-[var(--field-background)] px-3 py-2.5 text-sm"
              >
                <option value="">—</option>
                {(toursData?.items ?? []).map((tr) => (
                  <option key={tr.id} value={tr.slug}>{tt(tr.name, lang)}</option>
                ))}
              </select>
            </div>

            <TextField isInvalid={!!errors.message} isRequired className="sm:col-span-2">
              <Label>{t("inquiry.message")}</Label>
              <TextArea rows={5} value={form.message} onChange={(e) => set("message", e.target.value)} />
              <Description>{t("home.inquiryBody")}</Description>
              {errors.message && <FieldError>{errors.message}</FieldError>}
            </TextField>

            <div className="sm:col-span-2 flex flex-col gap-3">
              <Switch isSelected={form.flexibleDates} onChange={(v) => set("flexibleDates", v)}>
                <Switch.Content><Switch.Control><Switch.Thumb /></Switch.Control>{t("inquiry.flexible")}</Switch.Content>
              </Switch>
              <Switch isSelected={form.needTransport} onChange={(v) => set("needTransport", v)}>
                <Switch.Content><Switch.Control><Switch.Thumb /></Switch.Control>{t("inquiry.needTransport")}</Switch.Content>
              </Switch>
              <Checkbox isSelected={form.consent} onChange={(v) => set("consent", v)} isInvalid={!!errors.consent}>
                <Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>{t("inquiry.consent")}</Checkbox.Content>
              </Checkbox>
              {errors.consent && <p className="text-sm text-danger">{errors.consent}</p>}
              <Checkbox isSelected={form.marketingOptIn} onChange={(v) => set("marketingOptIn", v)}>
                <Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>{t("inquiry.marketing")}</Checkbox.Content>
              </Checkbox>
            </div>

            <div className="sm:col-span-2">
              <Button type="submit" variant="primary" size="lg" isDisabled={submit.isPending}>
                {submit.isPending ? <Spinner /> : t("actions.sendInquiry")}
              </Button>
            </div>
          </form>
        </Container>
      </Section>
    </>
  );
}
