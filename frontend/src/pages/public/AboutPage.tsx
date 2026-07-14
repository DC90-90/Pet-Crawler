import { useTranslation } from "react-i18next";
import { useSettings } from "@/lib/queries";
import { LangLink, useLang } from "@/lib/nav";
import { tt } from "@/i18n";
import { Button } from "@heroui/react";
import { Container, Section, MediaImage, SampleFlag } from "@/components/primitives";
import { Seo } from "@/components/site/Seo";

export function Component() {
  const { t } = useTranslation();
  const lang = useLang();
  const { data: settings } = useSettings();

  return (
    <>
      <Seo title={`${t("nav.about")} — Svaneti with Georgie`} description="Meet Georgie, a local guide from Mestia in Upper Svaneti." canonicalPath={`/${lang}/about-georgie`} />
      <Section>
        <Container>
          <div className="grid items-center gap-10 lg:grid-cols-2">
            <MediaImage url={settings?.ownerPortraitUrl} alt="Georgie, local guide from Mestia" ratio="aspect-[4/5]" className="rounded-3xl" />
            <div>
              <p className="text-sm font-semibold uppercase tracking-widest text-copper">A local guide</p>
              <h1 className="mt-2 font-display text-4xl font-medium">{t("nav.about")}</h1>
              <div className="mt-3"><SampleFlag show /></div>
              <div className="prose-alpine mt-4">
                {settings?.aboutText && tt(settings.aboutText, lang) ? (
                  <div dangerouslySetInnerHTML={{ __html: tt(settings.aboutText, lang) }} />
                ) : (
                  <p>
                    Georgie is a local guide from Mestia who helps visitors experience Svaneti
                    through local knowledge, flexible private tours, cultural understanding and
                    practical support. Details such as languages spoken, experience and
                    qualifications are managed by the owner and shown here once verified.
                  </p>
                )}
              </div>
              <LangLink to="/inquiry" className="mt-6 inline-block">
                <Button variant="primary">{t("actions.chatWithGeorgie")}</Button>
              </LangLink>
            </div>
          </div>
        </Container>
      </Section>
    </>
  );
}
