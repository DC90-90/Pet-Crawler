import { Spinner, Chip } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { useArticles } from "@/lib/queries";
import { LangLink, useLang } from "@/lib/nav";
import { tt } from "@/i18n";
import { Container, Section, SectionHeading, MediaImage } from "@/components/primitives";
import { Seo } from "@/components/site/Seo";

export function Component() {
  const { t } = useTranslation();
  const lang = useLang();
  const { data, isLoading } = useArticles();
  const items = data?.items ?? [];

  return (
    <>
      <Seo title={`${t("nav.travelGuide")} — Svaneti with Georgie`} description="Practical guides and stories for traveling in Svaneti." canonicalPath={`/${lang}/travel-guide`} />
      <Section>
        <Container>
          <SectionHeading as="h1" eyebrow="Stories & tips" title={t("nav.travelGuide")} intro={t("home.guideStories")} />
          {isLoading ? (
            <div className="grid min-h-64 place-items-center"><Spinner /></div>
          ) : items.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-border p-12 text-center text-muted">{t("misc.empty")}</div>
          ) : (
            <div className="grid gap-8 md:grid-cols-2 lg:grid-cols-3">
              {items.map((a) => (
                <LangLink key={a.id} to={`/travel-guide/${a.slug}`} className="group block">
                  <MediaImage url={a.coverUrl} alt={tt(a.title, lang)} ratio="aspect-[16/10]" className="rounded-2xl transition-transform duration-500 group-hover:scale-[1.02]" />
                  <div className="mt-3 flex flex-wrap gap-2">
                    {a.categories?.slice(0, 2).map((c) => <Chip key={c} size="sm" variant="soft">{c}</Chip>)}
                  </div>
                  <h2 className="mt-2 font-display text-xl leading-snug group-hover:text-copper">{tt(a.title, lang)}</h2>
                  <p className="mt-1 line-clamp-2 text-sm text-muted">{tt(a.excerpt, lang)}</p>
                  {a.readingMinutes && <p className="mt-2 text-xs text-muted">{a.readingMinutes} min read</p>}
                </LangLink>
              ))}
            </div>
          )}
        </Container>
      </Section>
    </>
  );
}
