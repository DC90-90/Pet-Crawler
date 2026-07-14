import { Card, Chip, Button, Spinner } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { useOffers } from "@/lib/queries";
import { LangLink, useLang } from "@/lib/nav";
import { tt } from "@/i18n";
import { Container, Section, SectionHeading } from "@/components/primitives";
import { Seo } from "@/components/site/Seo";

export function Component() {
  const { t } = useTranslation();
  const lang = useLang();
  const { data, isLoading } = useOffers();
  const items = data?.items ?? [];

  return (
    <>
      <Seo title={`${t("nav.offers")} — Svaneti with Georgie`} description="Seasonal offers and journeys in Svaneti." canonicalPath={`/${lang}/offers`} />
      <Section>
        <Container>
          <SectionHeading as="h1" eyebrow="Seasonal" title={t("nav.offers")} />
          {isLoading ? (
            <div className="grid min-h-64 place-items-center"><Spinner /></div>
          ) : items.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-border p-12 text-center text-muted">{t("misc.empty")}</div>
          ) : (
            <div className="grid gap-6 md:grid-cols-2">
              {items.map((o) => (
                <Card key={o.id} className="border-copper/30">
                  <Card.Header>
                    <Card.Title className="flex items-center gap-2">
                      {tt(o.title, lang)}
                      {o.code && <Chip size="sm" variant="soft" className="bg-copper/15 text-copper">{o.code}</Chip>}
                    </Card.Title>
                  </Card.Header>
                  <Card.Content>
                    <p className="text-sm text-muted">{tt(o.description, lang)}</p>
                    {o.terms && tt(o.terms, lang) && <p className="mt-3 text-xs text-muted">{tt(o.terms, lang)}</p>}
                  </Card.Content>
                  <Card.Footer>
                    <LangLink to={o.cta?.href ?? "/inquiry"}>
                      <Button variant="secondary" size="sm">{tt(o.cta?.label, lang) || t("actions.sendInquiry")}</Button>
                    </LangLink>
                  </Card.Footer>
                </Card>
              ))}
            </div>
          )}
        </Container>
      </Section>
    </>
  );
}
