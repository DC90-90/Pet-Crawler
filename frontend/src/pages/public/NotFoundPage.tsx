import { Button } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { LangLink } from "@/lib/nav";
import { Container } from "@/components/primitives";
import { Seo } from "@/components/site/Seo";

export function Component() {
  const { t } = useTranslation();
  return (
    <Container className="grid min-h-[60vh] place-items-center py-20 text-center">
      <Seo title="Not found — Svaneti with Georgie" noindex />
      <div>
        <p className="font-display text-7xl text-copper">404</p>
        <h1 className="mt-3 font-display text-2xl">{t("misc.notFound")}</h1>
        <LangLink to="/" className="mt-6 inline-block">
          <Button variant="primary">{t("misc.backHome")}</Button>
        </LangLink>
      </div>
    </Container>
  );
}
