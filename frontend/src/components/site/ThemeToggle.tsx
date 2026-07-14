import { Button } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { useThemeMode } from "@/lib/useUi";

export function ThemeToggle() {
  const { mode, toggle } = useThemeMode();
  const { t } = useTranslation();
  return (
    <Button
      variant="ghost"
      size="sm"
      isIconOnly
      aria-label={`${t("misc.theme")}: ${mode === "dark" ? "dark" : "light"}`}
      onPress={toggle}
    >
      <span aria-hidden className="text-base">
        {mode === "dark" ? "☾" : "☀"}
      </span>
    </Button>
  );
}
