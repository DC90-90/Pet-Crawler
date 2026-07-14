import { Spinner } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { useVideos } from "@/lib/queries";
import { useLang } from "@/lib/nav";
import { tt } from "@/i18n";
import { Container, Section, SectionHeading, MediaImage } from "@/components/primitives";
import { Seo } from "@/components/site/Seo";

export function Component() {
  const { t } = useTranslation();
  const lang = useLang();
  const { data, isLoading } = useVideos();
  const items = data?.items ?? [];

  return (
    <>
      <Seo title={`${t("nav.videos")} — Svaneti with Georgie`} description={t("home.storiesInMotion")} canonicalPath={`/${lang}/videos`} />
      <Section>
        <Container>
          <SectionHeading as="h1" eyebrow="Svaneti" title={t("nav.videos")} intro={t("home.storiesInMotion")} />
          {isLoading ? (
            <div className="grid min-h-64 place-items-center"><Spinner /></div>
          ) : (
            <div className="grid gap-6 md:grid-cols-2">
              {items.map((v) => (
                <figure key={v.id} className="overflow-hidden rounded-2xl border border-border">
                  {v.kind === "youtube" && v.externalUrl ? (
                    <div className="aspect-video">
                      <iframe className="h-full w-full" src={v.externalUrl.replace("watch?v=", "embed/")} title={tt(v.title, lang)} allow="accelerometer; encrypted-media; picture-in-picture" allowFullScreen />
                    </div>
                  ) : (
                    <MediaImage url={v.posterUrl} alt={tt(v.title, lang)} ratio="aspect-video" />
                  )}
                  <figcaption className="p-4">
                    <p className="font-display text-lg">{tt(v.title, lang)}</p>
                    {v.caption && <p className="text-sm text-muted">{tt(v.caption, lang)}</p>}
                  </figcaption>
                </figure>
              ))}
            </div>
          )}
        </Container>
      </Section>
    </>
  );
}
