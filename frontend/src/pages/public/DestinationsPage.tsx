import { Spinner } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { useDestinations } from "@/lib/queries";
import { LangLink, useLang } from "@/lib/nav";
import { tt } from "@/i18n";
import { Container, Section, SectionHeading, MediaImage } from "@/components/primitives";
import { Seo } from "@/components/site/Seo";

export function Component() {
  const { t } = useTranslation();
  const lang = useLang();
  const { data, isLoading } = useDestinations();
  const items = data?.items ?? [];

  return (
    <>
      <Seo title={`${t("nav.destinations")} — Svaneti with Georgie`} description={t("home.signatureDestinations")} canonicalPath={`/${lang}/destinations`} />
      <Section>
        <Container>
          <SectionHeading as="h1" eyebrow="Upper Svaneti" title={t("nav.destinations")} intro={t("home.signatureDestinations")} />
          {isLoading ? (
            <div className="grid min-h-64 place-items-center"><Spinner /></div>
          ) : (
            <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {items.map((d) => (
                <LangLink key={d.id} to={`/destinations/${d.slug}`} className="group block overflow-hidden rounded-2xl border border-border">
                  <div className="relative">
                    <MediaImage url={d.coverUrl} alt={tt(d.name, lang)} ratio="aspect-[3/2]" className="transition-transform duration-500 group-hover:scale-105" />
                  </div>
                  <div className="p-5">
                    <h2 className="font-display text-xl">{tt(d.name, lang)}</h2>
                    <p className="mt-1 line-clamp-2 text-sm text-muted">{tt(d.intro, lang)}</p>
                    {d.altitudeM && <p className="mt-2 text-xs text-copper">⛰ {d.altitudeM} m</p>}
                  </div>
                </LangLink>
              ))}
            </div>
          )}
        </Container>
      </Section>
    </>
  );
}
