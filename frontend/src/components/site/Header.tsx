import { useState } from "react";
import { Button, Drawer } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { LangLink } from "@/lib/nav";
import { useLang } from "@/lib/nav";
import { tt } from "@/i18n";
import { useNavigation, useSettings } from "@/lib/queries";
import { Container } from "@/components/primitives";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { ThemeToggle } from "./ThemeToggle";

const FALLBACK = [
  { key: "nav.tours", href: "/tours" },
  { key: "nav.destinations", href: "/destinations" },
  { key: "nav.experiences", href: "/experiences" },
  { key: "nav.travelGuide", href: "/travel-guide" },
  { key: "nav.gallery", href: "/gallery" },
  { key: "nav.about", href: "/about-georgie" },
];

export function Header() {
  const { t } = useTranslation();
  const lang = useLang();
  const [open, setOpen] = useState(false);
  const { data: nav } = useNavigation();
  const { data: settings } = useSettings();

  const brand = settings?.brandName ?? t("brand");
  const menu =
    nav?.mainMenu?.map((m) => ({ label: tt(m.label, lang), href: m.href })) ??
    FALLBACK.map((f) => ({ label: t(f.key), href: f.href }));

  return (
    <header className="sticky top-0 z-40 border-b border-border/70 bg-background/85 backdrop-blur-md">
      <Container>
        <div className="flex h-16 items-center justify-between gap-4">
          <LangLink to="/" className="flex items-center gap-2.5 shrink-0">
            <img src="/favicon.svg" alt="" className="h-8 w-8" aria-hidden />
            <span className="font-display text-lg font-medium leading-tight">{brand}</span>
          </LangLink>

          <nav aria-label="Primary" className="hidden items-center gap-1 lg:flex">
            {menu.map((m) => (
              <LangLink
                key={m.href}
                to={m.href}
                className="rounded-lg px-3 py-2 text-sm font-medium text-foreground/80 transition-colors hover:bg-default/60 hover:text-foreground"
              >
                {m.label}
              </LangLink>
            ))}
          </nav>

          <div className="flex items-center gap-1.5">
            <div className="hidden sm:block">
              <LanguageSwitcher />
            </div>
            <ThemeToggle />
            <LangLink to="/inquiry" className="hidden sm:inline-flex">
              <Button variant="primary" size="sm">
                {t("actions.sendInquiry")}
              </Button>
            </LangLink>
            <div className="lg:hidden">
              <Button
                variant="ghost"
                size="sm"
                isIconOnly
                aria-label={t("actions.menu")}
                onPress={() => setOpen(true)}
              >
                <span aria-hidden className="text-lg">☰</span>
              </Button>
            </div>
          </div>
        </div>
      </Container>

      <Drawer isOpen={open} onOpenChange={setOpen}>
        <Drawer.Backdrop>
          <Drawer.Content>
            <Drawer.Dialog>
              <Drawer.CloseTrigger />
              <Drawer.Header>
                <Drawer.Heading>{brand}</Drawer.Heading>
              </Drawer.Header>
              <Drawer.Body>
                <nav aria-label="Mobile" className="flex flex-col gap-1">
                  {menu.map((m) => (
                    <LangLink
                      key={m.href}
                      to={m.href}
                      onClick={() => setOpen(false)}
                      className="rounded-lg px-3 py-3 text-base font-medium hover:bg-default/60"
                    >
                      {m.label}
                    </LangLink>
                  ))}
                </nav>
                <div className="mt-4 flex items-center gap-2">
                  <LanguageSwitcher />
                </div>
              </Drawer.Body>
              <Drawer.Footer>
                <LangLink to="/inquiry" onClick={() => setOpen(false)} className="w-full">
                  <Button variant="primary" className="w-full">
                    {t("actions.sendInquiry")}
                  </Button>
                </LangLink>
              </Drawer.Footer>
            </Drawer.Dialog>
          </Drawer.Content>
        </Drawer.Backdrop>
      </Drawer>
    </header>
  );
}
