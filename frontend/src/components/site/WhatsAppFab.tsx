import { useTranslation } from "react-i18next";
import { useSettings } from "@/lib/queries";

/** Sticky messaging CTA. Uses WhatsApp when a number is configured, else the inquiry form. */
export function WhatsAppFab() {
  const { t } = useTranslation();
  const { data: settings } = useSettings();
  const wa = settings?.contact?.whatsapp?.replace(/[^0-9]/g, "");
  const href = wa ? `https://wa.me/${wa}` : "./inquiry";

  return (
    <a
      href={href}
      target={wa ? "_blank" : undefined}
      rel={wa ? "noopener noreferrer" : undefined}
      aria-label={t("actions.chatWithGeorgie")}
      className="fixed bottom-5 end-5 z-30 flex items-center gap-2 rounded-full bg-copper px-4 py-3 text-sm font-semibold text-white shadow-lg transition-transform hover:scale-105 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-copper"
    >
      <span aria-hidden className="text-lg">💬</span>
      <span className="hidden sm:inline">{t("actions.chatWithGeorgie")}</span>
    </a>
  );
}
