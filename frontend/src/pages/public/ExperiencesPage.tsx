import { useTranslation } from "react-i18next";
import { useTours } from "@/lib/queries";
import { Container, Section, SectionHeading } from "@/components/primitives";
import { TourCard } from "@/components/content/TourCard";
import { useLang } from "@/lib/nav";
import { Seo } from "@/components/site/Seo";

const THEMES = [
  { key: "hiking", label: "Hiking & trekking", filter: { difficulty: "moderate" } },
  { key: "culture", label: "Culture & villages", filter: {} },
  { key: "family", label: "Family & low-activity", filter: { family: true } },
  { key: "winter", label: "Winter & transfers", filter: { winter: true } },
];

function ThemeRow({ label, filter }: { label: string; filter: Record<string, unknown> }) {
  const { data } = useTours({ ...filter, pageSize: 3 });
  const items = (data?.items ?? []).slice(0, 3);
  if (items.length === 0) return null;
  return (
    <div className="mb-12">
      <h2 className="mb-4 font-display text-2xl">{label}</h2>
      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((tour) => <TourCard key={tour.id} tour={tour} />)}
      </div>
    </div>
  );
}

export function Component() {
  const { t } = useTranslation();
  const lang = useLang();
  return (
    <>
      <Seo title={`${t("nav.experiences")} — Svaneti with Georgie`} description="Ways to experience Svaneti — hiking, culture, family and winter." canonicalPath={`/${lang}/experiences`} />
      <Section>
        <Container>
          <SectionHeading as="h1" eyebrow="Ways to travel" title={t("nav.experiences")} intro={t("home.seasonal")} />
          {THEMES.map((th) => <ThemeRow key={th.key} label={th.label} filter={th.filter} />)}
        </Container>
      </Section>
    </>
  );
}
