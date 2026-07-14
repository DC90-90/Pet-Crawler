import { useMemo, useState } from "react";
import { Button, Chip, SearchField, Select, ListBox, Label, Switch, Spinner } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { useTours } from "@/lib/queries";
import { useLang } from "@/lib/nav";
import { Container, Section, SectionHeading } from "@/components/primitives";
import { TourCard } from "@/components/content/TourCard";
import { Seo } from "@/components/site/Seo";
import { HelpMeChoose } from "@/components/content/HelpMeChoose";

const DIFFICULTIES = ["easy", "moderate", "challenging", "strenuous"];
const SEASONS = ["spring", "summer", "autumn", "winter"];

export function Component() {
  const { t } = useTranslation();
  const lang = useLang();
  const [q, setQ] = useState("");
  const [difficulty, setDifficulty] = useState<string>("");
  const [season, setSeason] = useState<string>("");
  const [sort, setSort] = useState<string>("featured");
  const [flags, setFlags] = useState({ family: false, lowWalking: false, winter: false, private: false });
  const [helpOpen, setHelpOpen] = useState(false);

  const filters = useMemo(
    () => ({
      q: q || undefined,
      difficulty: difficulty || undefined,
      season: season || undefined,
      sort,
      family: flags.family || undefined,
      lowWalking: flags.lowWalking || undefined,
      winter: flags.winter || undefined,
      private: flags.private || undefined,
    }),
    [q, difficulty, season, sort, flags],
  );

  const { data, isLoading } = useTours(filters);
  const items = data?.items ?? [];

  return (
    <>
      <Seo title={`${t("nav.tours")} — Svaneti with Georgie`} description={t("home.inquiryBody")} canonicalPath={`/${lang}/tours`} />
      <Section>
        <Container>
          <SectionHeading as="h1" eyebrow="Svaneti" title={t("nav.tours")} intro={t("home.inquiryBody")} />

          <div className="mb-8 flex flex-col gap-4 rounded-2xl border border-border bg-surface/50 p-4 sm:p-5">
            <div className="flex flex-col gap-3 md:flex-row md:items-end">
              <div className="flex-1">
                <SearchField value={q} onChange={setQ} aria-label={t("actions.search")}>
                  <Label className="text-sm font-medium">{t("actions.search")}</Label>
                  <SearchField.Group>
                    <SearchField.SearchIcon />
                    <SearchField.Input placeholder="Ushguli, glacier, family…" />
                  </SearchField.Group>
                </SearchField>
              </div>

              <Select selectedKey={difficulty} onSelectionChange={(k) => setDifficulty(String(k ?? ""))}>
                <Label className="text-sm font-medium">{t("labels.difficulty")}</Label>
                <Select.Trigger className="min-w-40">
                  <Select.Value />
                  <Select.Indicator />
                </Select.Trigger>
                <Select.Popover>
                  <ListBox>
                    <ListBox.Item id="">All</ListBox.Item>
                    {DIFFICULTIES.map((d) => (
                      <ListBox.Item key={d} id={d} className="capitalize">
                        {d}
                      </ListBox.Item>
                    ))}
                  </ListBox>
                </Select.Popover>
              </Select>

              <Select selectedKey={season} onSelectionChange={(k) => setSeason(String(k ?? ""))}>
                <Label className="text-sm font-medium">{t("labels.season")}</Label>
                <Select.Trigger className="min-w-40">
                  <Select.Value />
                  <Select.Indicator />
                </Select.Trigger>
                <Select.Popover>
                  <ListBox>
                    <ListBox.Item id="">All</ListBox.Item>
                    {SEASONS.map((s) => (
                      <ListBox.Item key={s} id={s} className="capitalize">
                        {s}
                      </ListBox.Item>
                    ))}
                  </ListBox>
                </Select.Popover>
              </Select>

              <Select selectedKey={sort} onSelectionChange={(k) => setSort(String(k ?? "featured"))}>
                <Label className="text-sm font-medium">Sort</Label>
                <Select.Trigger className="min-w-40">
                  <Select.Value />
                  <Select.Indicator />
                </Select.Trigger>
                <Select.Popover>
                  <ListBox>
                    <ListBox.Item id="featured">Featured</ListBox.Item>
                    <ListBox.Item id="duration">Duration</ListBox.Item>
                    <ListBox.Item id="newest">Newest</ListBox.Item>
                  </ListBox>
                </Select.Popover>
              </Select>
            </div>

            <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
              <Switch isSelected={flags.family} onChange={(v) => setFlags((f) => ({ ...f, family: v }))}>
                <Switch.Content><Switch.Control><Switch.Thumb /></Switch.Control>{t("labels.familyFriendly")}</Switch.Content>
              </Switch>
              <Switch isSelected={flags.lowWalking} onChange={(v) => setFlags((f) => ({ ...f, lowWalking: v }))}>
                <Switch.Content><Switch.Control><Switch.Thumb /></Switch.Control>{t("labels.lowWalking")}</Switch.Content>
              </Switch>
              <Switch isSelected={flags.winter} onChange={(v) => setFlags((f) => ({ ...f, winter: v }))}>
                <Switch.Content><Switch.Control><Switch.Thumb /></Switch.Control>{t("labels.winter")}</Switch.Content>
              </Switch>
              <Switch isSelected={flags.private} onChange={(v) => setFlags((f) => ({ ...f, private: v }))}>
                <Switch.Content><Switch.Control><Switch.Thumb /></Switch.Control>{t("labels.private")}</Switch.Content>
              </Switch>
              <div className="ms-auto">
                <Button variant="secondary" onPress={() => setHelpOpen(true)}>
                  🧭 {t("actions.helpMeChoose")}
                </Button>
              </div>
            </div>
          </div>

          {isLoading ? (
            <div className="grid min-h-64 place-items-center"><Spinner /></div>
          ) : items.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-border p-12 text-center text-muted">
              {t("misc.empty")}
            </div>
          ) : (
            <>
              <p className="mb-4 text-sm text-muted">
                <Chip size="sm" variant="soft">{items.length}</Chip> {t("nav.tours").toLowerCase()}
              </p>
              <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
                {items.map((tour) => (
                  <TourCard key={tour.id} tour={tour} />
                ))}
              </div>
            </>
          )}
        </Container>
      </Section>

      <HelpMeChoose isOpen={helpOpen} onOpenChange={setHelpOpen} />
    </>
  );
}
