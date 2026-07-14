import { useParams } from "react-router-dom";
import { Spinner } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { useDestination } from "@/lib/queries";
import { LangLink, useLang } from "@/lib/nav";
import { tt } from "@/i18n";
import { Container, Section, MediaImage } from "@/components/primitives";
import { Seo } from "@/components/site/Seo";

export function Component() {
  const { slug } = useParams();
  const lang = useLang();
  const { t } = useTranslation();
  const { data: d, isLoading, isError } = useDestination(slug ?? "");

  if (isLoading) return <div className="grid min-h-[60vh] place-items-center"><Spinner /></div>;
  if (isError || !d)
    return (
      <Container className="py-24 text-center">
        <p className="text-muted">{t("misc.notFound")}</p>
      </Container>
    );

  return (
    <>
      <Seo
        title={`${tt(d.name, lang)} — Svaneti with Georgie`}
        description={tt(d.intro, lang)}
        ogImage={d.coverUrl}
        canonicalPath={`/${lang}/destinations/${d.slug}`}
        jsonLd={{ "@context": "https://schema.org", "@type": "TouristAttraction", name: tt(d.name, lang), description: tt(d.intro, lang) }}
      />
      <section className="relative isolate text-white">
        <div className="absolute inset-0 -z-10">
          <MediaImage url={d.coverUrl} alt={tt(d.name, lang)} ratio="h-full" loading="eager" />
          <div className="absolute inset-0 bg-black/45" />
        </div>
        <Container className="flex min-h-[46vh] flex-col justify-end py-16">
          <nav aria-label="Breadcrumb" className="mb-3 text-sm text-white/75">
            <LangLink to="/destinations" className="hover:underline">{t("nav.destinations")}</LangLink>
            <span className="mx-2">/</span>
            <span>{tt(d.name, lang)}</span>
          </nav>
          <h1 className="font-display text-4xl font-medium sm:text-5xl">{tt(d.name, lang)}</h1>
        </Container>
      </section>

      <Section>
        <Container size="narrow">
          <p className="text-lg text-foreground/90">{tt(d.intro, lang)}</p>
          {d.description && <div className="prose-alpine mt-6" dangerouslySetInnerHTML={{ __html: tt(d.description, lang) }} />}
          {d.culturalNotes && tt(d.culturalNotes, lang) && (
            <div className="mt-8">
              <h2 className="font-display text-2xl">Culture</h2>
              <p className="mt-2 text-muted">{tt(d.culturalNotes, lang)}</p>
            </div>
          )}
          {d.practicalAdvice && tt(d.practicalAdvice, lang) && (
            <div className="mt-8 rounded-xl border border-border bg-surface/60 p-5">
              <h2 className="font-semibold">Practical advice</h2>
              <p className="mt-2 text-sm text-muted">{tt(d.practicalAdvice, lang)}</p>
            </div>
          )}
        </Container>
        {d.galleryUrls && d.galleryUrls.length > 0 && (
          <Container className="mt-12">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {d.galleryUrls.map((u, i) => (
                <MediaImage key={i} url={u} alt={`${tt(d.name, lang)} ${i + 1}`} ratio="aspect-square" className="rounded-xl" />
              ))}
            </div>
          </Container>
        )}
      </Section>
    </>
  );
}
