import { useParams } from "react-router-dom";
import { Spinner } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { useArticle } from "@/lib/queries";
import { LangLink, useLang } from "@/lib/nav";
import { tt } from "@/i18n";
import { Container, Section, MediaImage, SampleFlag } from "@/components/primitives";
import { Seo } from "@/components/site/Seo";

export function Component() {
  const { slug } = useParams();
  const lang = useLang();
  const { t } = useTranslation();
  const { data: a, isLoading, isError } = useArticle(slug ?? "");

  if (isLoading) return <div className="grid min-h-[60vh] place-items-center"><Spinner /></div>;
  if (isError || !a)
    return <Container className="py-24 text-center"><p className="text-muted">{t("misc.notFound")}</p></Container>;

  return (
    <>
      <Seo
        title={`${tt(a.title, lang)} — Svaneti with Georgie`}
        description={tt(a.excerpt, lang)}
        ogImage={a.coverUrl}
        canonicalPath={`/${lang}/travel-guide/${a.slug}`}
        jsonLd={{ "@context": "https://schema.org", "@type": "Article", headline: tt(a.title, lang), description: tt(a.excerpt, lang), author: a.author, datePublished: a.publishedAt }}
      />
      <Section>
        <Container size="narrow">
          <nav aria-label="Breadcrumb" className="mb-4 text-sm text-muted">
            <LangLink to="/travel-guide" className="hover:underline">{t("nav.travelGuide")}</LangLink>
            <span className="mx-2">/</span>
            <span>{tt(a.title, lang)}</span>
          </nav>
          <h1 className="font-display text-3xl font-medium sm:text-4xl">{tt(a.title, lang)}</h1>
          <div className="mt-2 flex items-center gap-3 text-sm text-muted">
            {a.author && <span>By {a.author}</span>}
            {a.readingMinutes && <span>· {a.readingMinutes} min read</span>}
            <SampleFlag show={a.verificationStatus === "needs_verification"} />
          </div>
        </Container>
        {a.coverUrl && (
          <Container size="narrow" className="mt-6">
            <MediaImage url={a.coverUrl} alt={tt(a.title, lang)} ratio="aspect-[16/9]" className="rounded-2xl" />
          </Container>
        )}
        <Container size="narrow" className="mt-8">
          <p className="text-lg text-foreground/90">{tt(a.excerpt, lang)}</p>
          {a.body && <div className="prose-alpine mt-6" dangerouslySetInnerHTML={{ __html: tt(a.body, lang) }} />}
        </Container>
      </Section>
    </>
  );
}
