import { Tabs, TextField, Input, TextArea, Label } from "@heroui/react";
import type { Lang, LocalizedText } from "@/lib/types";

const LANGS: { id: Lang; label: string }[] = [
  { id: "en", label: "English" },
  { id: "ka", label: "ქართული" },
  { id: "ar", label: "العربية" },
];

/**
 * Tabbed localized text editor bound to a `LocalizedText` value.
 * English is required; ka/ar are optional. Arabic panel renders RTL.
 */
export function LocalizedInput({
  label,
  value,
  onChange,
  multiline = false,
  rows = 4,
  placeholder,
  hint,
}: {
  label: string;
  value: LocalizedText | undefined;
  onChange: (v: LocalizedText) => void;
  multiline?: boolean;
  rows?: number;
  placeholder?: string;
  hint?: string;
}) {
  const current: LocalizedText = value ?? { en: "" };

  const setLang = (lang: Lang, text: string) => {
    onChange({ ...current, en: current.en ?? "", [lang]: text });
  };

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-medium text-foreground">{label}</span>
        {hint && <span className="text-xs text-muted">{hint}</span>}
      </div>
      <Tabs defaultSelectedKey="en">
        <Tabs.ListContainer>
          <Tabs.List aria-label={`${label} translations`}>
            {LANGS.map((l) => (
              <Tabs.Tab key={l.id} id={l.id}>
                {l.label}
                {l.id === "en" ? " *" : ""}
                <Tabs.Indicator />
              </Tabs.Tab>
            ))}
          </Tabs.List>
        </Tabs.ListContainer>
        {LANGS.map((l) => (
          <Tabs.Panel key={l.id} id={l.id}>
            <div dir={l.id === "ar" ? "rtl" : "ltr"} className="pt-2">
              <TextField
                value={current[l.id] ?? ""}
                onChange={(t) => setLang(l.id, t)}
                aria-label={`${label} (${l.label})`}
                className="flex flex-col gap-1"
              >
                <Label className="sr-only">{`${label} (${l.label})`}</Label>
                {multiline ? (
                  <TextArea rows={rows} placeholder={placeholder} />
                ) : (
                  <Input placeholder={placeholder} />
                )}
              </TextField>
            </div>
          </Tabs.Panel>
        ))}
      </Tabs>
    </div>
  );
}
