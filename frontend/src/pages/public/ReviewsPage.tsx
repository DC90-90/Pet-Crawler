import { Card, Spinner } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { useReviews } from "@/lib/queries";
import { useLang } from "@/lib/nav";
import { Container, Section, SectionHeading, Stars, SampleFlag } from "@/components/primitives";
import { Seo } from "@/components/site/Seo";

export function Component() {
  const { t } = useTranslation();
  const lang = useLang();
  const { data, isLoading } = useReviews();
  const items = data?.items ?? [];

  return (
    <>
      <Seo title={`${t("nav.reviews")} — Svaneti with Georgie`} description="Traveler reviews for journeys in Svaneti." canonicalPath={`/${lang}/reviews`} />
      <Section>
        <Container>
          <SectionHeading as="h1" eyebrow="Travelers" title={t("nav.reviews")} />
          {isLoading ? (
            <div className="grid min-h-64 place-items-center"><Spinner /></div>
          ) : items.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-border p-12 text-center text-muted">{t("misc.empty")}</div>
          ) : (
            <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
              {items.map((r) => (
                <Card key={r.id}>
                  <Card.Content className="pt-6">
                    <div className="mb-2 flex items-center justify-between">
                      <Stars rating={r.rating} />
                      <SampleFlag show={r.isSample} />
                    </div>
                    <p className="text-sm text-foreground/90">“{r.text}”</p>
                    <p className="mt-3 text-sm font-semibold">
                      {r.reviewerName}
                      {r.country && <span className="font-normal text-muted"> · {r.country}</span>}
                    </p>
                    {r.source && <p className="text-xs text-muted">via {r.source}</p>}
                  </Card.Content>
                </Card>
              ))}
            </div>
          )}
        </Container>
      </Section>
    </>
  );
}
