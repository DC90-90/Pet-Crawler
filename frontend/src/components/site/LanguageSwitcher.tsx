import { Button, Dropdown } from "@heroui/react";
import { useNavigate, useLocation, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { SUPPORTED_LANGS } from "@/i18n";
import type { Lang } from "@/lib/types";

const LABELS: Record<Lang, string> = { en: "English", ka: "ქართული", ar: "العربية" };
const SHORT: Record<Lang, string> = { en: "EN", ka: "KA", ar: "AR" };

export function LanguageSwitcher() {
  const { lang } = useParams();
  const current = (SUPPORTED_LANGS.includes(lang as never) ? lang : "en") as Lang;
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation();

  const switchTo = (next: Lang) => {
    // Swap the first path segment (the language) and keep the rest of the route.
    const rest = location.pathname.replace(/^\/[^/]+/, "");
    navigate(`/${next}${rest}${location.search}`);
  };

  return (
    <Dropdown>
      <Button variant="ghost" size="sm" aria-label={t("misc.language")}>
        <span aria-hidden>🌐</span>
        <span className="ms-1 font-semibold">{SHORT[current]}</span>
      </Button>
      <Dropdown.Popover>
        <Dropdown.Menu
          aria-label={t("misc.language")}
          onAction={(key) => switchTo(String(key) as Lang)}
        >
          {SUPPORTED_LANGS.map((l) => (
            <Dropdown.Item key={l} id={l}>
              {LABELS[l]}
            </Dropdown.Item>
          ))}
        </Dropdown.Menu>
      </Dropdown.Popover>
    </Dropdown>
  );
}
