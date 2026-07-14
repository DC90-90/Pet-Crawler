import { Button } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { useSettings } from "@/lib/queries";
import { LangLink, useLang } from "@/lib/nav";
import { Container, Section, SectionHeading } from "@/components/primitives";
import { SvanetiMap } from "@/components/content/SvanetiMap";
import { Seo } from "@/components/site/Seo";

export function Component() {
  const { t } = useTranslation();
  const lang = useLang();
  const { data: s } = useSettings();
  const wa = s?.contact?.whatsapp?.replace(/[^0-9]/g, "");

  return (
    <>
      <Seo title={`${t("nav.contact")} — Svaneti with Georgie`} description="Contact Georgie to plan your Svaneti journey." canonicalPath={`/${lang}/contact`} />
      <Section>
        <Container>
          <SectionHeading as="h1" eyebrow="Say hello" title={t("nav.contact")} intro={t("home.inquiryBody")} />
          <div className="grid gap-10 lg:grid-cols-2">
            <div className="space-y-4">
              <ul className="space-y-3 text-sm">
                {s?.contact?.email && <li>✉️ <a className="text-copper hover:underline" href={`mailto:${s.contact.email}`}>{s.contact.email}</a></li>}
                {wa && <li>💬 <a className="text-copper hover:underline" href={`https://wa.me/${wa}`} target="_blank" rel="noopener noreferrer">WhatsApp</a></li>}
                {s?.contact?.phone && <li>📞 {s.contact.phone}</li>}
                {s?.contact?.region && <li>📍 {s.contact.region}</li>}
              </ul>
              <p className="text-sm text-muted">{t("misc.needsVerification")} — contact details are managed by the owner.</p>
              <LangLink to="/inquiry"><Button variant="primary">{t("actions.sendInquiry")}</Button></LangLink>
            </div>
            <SvanetiMap />
          </div>
        </Container>
      </Section>
    </>
  );
}
