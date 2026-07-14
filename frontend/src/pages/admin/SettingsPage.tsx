import { useEffect, useState } from "react";
import { Button, Chip, Separator } from "@heroui/react";
import {
  useSettings,
  useUpdateSettings,
  useMe,
  errMessage,
  type AdminSettings,
} from "@/lib/admin";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { LoadingState, ErrorState } from "@/components/admin/AdminEmptyState";
import { LocalizedInput } from "@/components/admin/LocalizedInput";
import { MediaPicker } from "@/components/admin/MediaPicker";
import {
  FormCard,
  FieldGrid,
  TextInput,
  SelectInput,
  SwitchInput,
  CheckboxInput,
} from "@/components/admin/FormField";
import { LANG_OPTIONS } from "@/components/admin/constants";

function VerifyBadge() {
  return (
    <Chip size="sm" variant="soft" color="warning">
      needs owner verification
    </Chip>
  );
}

const ALL_LANGS = ["en", "ka", "ar"];

export function Component() {
  const { data: me } = useMe();
  const { data, isLoading, isError, error } = useSettings();
  const update = useUpdateSettings();
  const [s, setS] = useState<Partial<AdminSettings>>({});

  useEffect(() => {
    if (data) setS(data);
  }, [data]);

  if (isLoading) return <LoadingState />;
  if (isError) return <ErrorState message={errMessage(error)} />;

  const isOwner = me?.role === "owner";
  const set = <K extends keyof AdminSettings>(k: K, v: AdminSettings[K]) =>
    setS((prev) => ({ ...prev, [k]: v }));

  const langs = s.supportedLanguages ?? [];
  const toggleLang = (lang: string) =>
    set(
      "supportedLanguages",
      langs.includes(lang) ? langs.filter((l) => l !== lang) : [...langs, lang],
    );

  const contact = s.contact ?? {};
  const analytics = s.analytics ?? {};
  const emergency = s.emergencyNotice ?? { enabled: false, text: { en: "" } };

  return (
    <div>
      <AdminPageHeader
        title="Settings"
        description="Brand, contact, languages and site-wide configuration."
        actions={
          <Button
            variant="primary"
            size="sm"
            onPress={() => update.mutate(s)}
            isDisabled={update.isPending}
          >
            {update.isPending ? "Saving…" : "Save settings"}
          </Button>
        }
      />

      <div className="flex flex-col gap-6">
        <FormCard title="Brand">
          <TextInput
            label="Brand name"
            value={s.brandName ?? ""}
            onChange={(v) => set("brandName", v)}
          />
          <LocalizedInput
            label="Tagline"
            value={s.tagline}
            onChange={(v) => set("tagline", v)}
          />
          <LocalizedInput
            label="About text"
            multiline
            rows={4}
            value={s.aboutText}
            onChange={(v) => set("aboutText", v)}
          />
          <div className="grid gap-4 sm:grid-cols-3">
            <MediaPicker
              label="Logo"
              value={s.logoMediaId}
              onChange={(id) => set("logoMediaId", id)}
            />
            <MediaPicker
              label="Favicon"
              value={s.faviconMediaId}
              onChange={(id) => set("faviconMediaId", id)}
            />
            <MediaPicker
              label="Owner portrait"
              value={s.ownerPortraitMediaId}
              onChange={(id) => set("ownerPortraitMediaId", id)}
            />
          </div>
        </FormCard>

        <FormCard title="Contact">
          <div className="flex items-center gap-2 text-sm text-muted">
            Verify these against Georgie's real details <VerifyBadge />
          </div>
          <FieldGrid>
            <TextInput
              label="Phone"
              value={contact.phone ?? ""}
              onChange={(v) => set("contact", { ...contact, phone: v })}
            />
            <TextInput
              label="WhatsApp"
              value={contact.whatsapp ?? ""}
              onChange={(v) => set("contact", { ...contact, whatsapp: v })}
            />
            <TextInput
              label="Email"
              type="email"
              value={contact.email ?? ""}
              onChange={(v) => set("contact", { ...contact, email: v })}
            />
            <TextInput
              label="Region"
              value={contact.region ?? ""}
              onChange={(v) => set("contact", { ...contact, region: v })}
            />
          </FieldGrid>
        </FormCard>

        <FormCard title="Social links">
          {(s.socials ?? []).map((soc, i) => (
            <div key={i} className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
              <TextInput
                label="Platform"
                value={soc.platform}
                onChange={(v) =>
                  set(
                    "socials",
                    (s.socials ?? []).map((x, idx) =>
                      idx === i ? { ...x, platform: v } : x,
                    ),
                  )
                }
              />
              <TextInput
                label="URL"
                value={soc.url}
                onChange={(v) =>
                  set(
                    "socials",
                    (s.socials ?? []).map((x, idx) => (idx === i ? { ...x, url: v } : x)),
                  )
                }
              />
              <div className="flex items-end">
                <Button
                  variant="tertiary"
                  size="sm"
                  aria-label="Remove social"
                  onPress={() =>
                    set("socials", (s.socials ?? []).filter((_, idx) => idx !== i))
                  }
                >
                  ✕
                </Button>
              </div>
            </div>
          ))}
          <div>
            <Button
              variant="outline"
              size="sm"
              onPress={() =>
                set("socials", [...(s.socials ?? []), { platform: "", url: "" }])
              }
            >
              Add social link
            </Button>
          </div>
        </FormCard>

        <FormCard title="Languages & currency">
          <div>
            <p className="mb-2 text-sm font-medium text-foreground">Supported languages</p>
            <div className="flex flex-wrap gap-4">
              {ALL_LANGS.map((lang) => (
                <CheckboxInput
                  key={lang}
                  label={lang.toUpperCase()}
                  value={langs.includes(lang)}
                  onChange={() => toggleLang(lang)}
                />
              ))}
            </div>
          </div>
          <FieldGrid>
            <SelectInput
              label="Default language"
              value={s.defaultLanguage}
              onChange={(v) => set("defaultLanguage", v)}
              options={LANG_OPTIONS}
            />
            <TextInput
              label="Currency"
              value={s.currency ?? ""}
              onChange={(v) => set("currency", v)}
              placeholder="GEL"
            />
            <TextInput
              label="Timezone"
              value={s.timezone ?? ""}
              onChange={(v) => set("timezone", v)}
              placeholder="Asia/Tbilisi"
            />
          </FieldGrid>
        </FormCard>

        <FormCard title="Cookie & emergency notices">
          <LocalizedInput
            label="Cookie notice"
            multiline
            rows={2}
            value={s.cookieNotice}
            onChange={(v) => set("cookieNotice", v)}
          />
          <Separator />
          <SwitchInput
            label="Show emergency notice"
            value={!!emergency.enabled}
            onChange={(v) => set("emergencyNotice", { ...emergency, enabled: v })}
          />
          <LocalizedInput
            label="Emergency notice text"
            multiline
            rows={2}
            value={emergency.text}
            onChange={(v) => set("emergencyNotice", { ...emergency, text: v })}
          />
        </FormCard>

        <FormCard title="Global call-to-action">
          <LocalizedInput
            label="CTA label"
            value={s.globalCta?.label}
            onChange={(v) =>
              set("globalCta", { label: v, href: s.globalCta?.href ?? "" })
            }
          />
          <TextInput
            label="CTA href"
            value={s.globalCta?.href ?? ""}
            onChange={(v) =>
              set("globalCta", { label: s.globalCta?.label ?? { en: "" }, href: v })
            }
          />
        </FormCard>

        {/* Owner-only: analytics / secrets */}
        {isOwner ? (
          <FormCard
            title="Analytics & verification"
            description="Owner only. These IDs are sensitive."
          >
            <div className="flex items-center gap-2 text-sm text-muted">
              Confirm before enabling in production <VerifyBadge />
            </div>
            <FieldGrid>
              <TextInput
                label="Google Analytics ID"
                value={analytics.gaId ?? ""}
                onChange={(v) => set("analytics", { ...analytics, gaId: v })}
                placeholder="G-XXXXXXX"
              />
              <TextInput
                label="Search Console verification"
                value={analytics.gscVerification ?? ""}
                onChange={(v) => set("analytics", { ...analytics, gscVerification: v })}
              />
              <TextInput
                label="Meta Pixel ID"
                value={analytics.metaPixelId ?? ""}
                onChange={(v) => set("analytics", { ...analytics, metaPixelId: v })}
              />
            </FieldGrid>
          </FormCard>
        ) : (
          <FormCard title="Analytics & verification">
            <p className="text-sm text-muted">
              Analytics settings are restricted to the site owner.
            </p>
          </FormCard>
        )}
      </div>
    </div>
  );
}
