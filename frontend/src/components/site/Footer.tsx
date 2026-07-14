import { useTranslation } from "react-i18next";
import { LangLink, useLang } from "@/lib/nav";
import { tt } from "@/i18n";
import { useNavigation, useSettings } from "@/lib/queries";
import { Container } from "@/components/primitives";

export function Footer() {
  const { t } = useTranslation();
  const lang = useLang();
  const { data: nav } = useNavigation();
  const { data: settings } = useSettings();
  const brand = settings?.brandName ?? t("brand");
  const year = new Date().getFullYear();

  const groups = nav?.footerGroups ?? [];
  const legal = nav?.legalLinks ?? [
    { label: { en: "Privacy" }, href: "/privacy" },
    { label: { en: "Terms" }, href: "/terms" },
  ];

  return (
    <footer className="mt-8 border-t border-border bg-surface/60">
      <Container className="py-14">
        <div className="grid gap-10 md:grid-cols-[1.4fr_repeat(3,1fr)]">
          <div>
            <div className="flex items-center gap-2.5">
              <img src="/favicon.svg" alt="" className="h-8 w-8" aria-hidden />
              <span className="font-display text-lg font-medium">{brand}</span>
            </div>
            <p className="mt-3 max-w-xs text-sm text-muted">{tt(settings?.tagline, lang)}</p>
            {settings?.contact?.whatsapp && (
              <a
                href={`https://wa.me/${settings.contact.whatsapp.replace(/[^0-9]/g, "")}`}
                className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-copper hover:underline"
              >
                <span aria-hidden>💬</span> WhatsApp
              </a>
            )}
          </div>

          {groups.length > 0
            ? groups.map((g, i) => (
                <nav key={i} aria-label={tt(g.title, lang)}>
                  <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-foreground">
                    {tt(g.title, lang)}
                  </h3>
                  <ul className="space-y-2">
                    {g.links.map((l, j) => (
                      <li key={j}>
                        <LangLink to={l.href} className="text-sm text-muted hover:text-foreground">
                          {tt(l.label, lang)}
                        </LangLink>
                      </li>
                    ))}
                  </ul>
                </nav>
              ))
            : (
                <nav aria-label="Explore">
                  <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider">
                    {t("nav.tours")}
                  </h3>
                  <ul className="space-y-2 text-sm text-muted">
                    <li><LangLink to="/tours" className="hover:text-foreground">{t("nav.tours")}</LangLink></li>
                    <li><LangLink to="/destinations" className="hover:text-foreground">{t("nav.destinations")}</LangLink></li>
                    <li><LangLink to="/travel-guide" className="hover:text-foreground">{t("nav.travelGuide")}</LangLink></li>
                    <li><LangLink to="/plan-your-trip" className="hover:text-foreground">{t("nav.planTrip")}</LangLink></li>
                  </ul>
                </nav>
              )}
        </div>

        <div className="mt-12 flex flex-col items-start justify-between gap-4 border-t border-border pt-6 sm:flex-row sm:items-center">
          <p className="text-xs text-muted">
            © {year} {brand}. {t("misc.needsVerification")} — see owner checklist.
          </p>
          <ul className="flex gap-4 text-xs text-muted">
            {legal.map((l, i) => (
              <li key={i}>
                <LangLink to={l.href} className="hover:text-foreground">
                  {tt(l.label, lang)}
                </LangLink>
              </li>
            ))}
          </ul>
        </div>
      </Container>
    </footer>
  );
}
