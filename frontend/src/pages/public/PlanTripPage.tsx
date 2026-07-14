import { useTranslation } from "react-i18next";
import { useLang } from "@/lib/nav";
import { Container, Section, SectionHeading } from "@/components/primitives";
import { Seo } from "@/components/site/Seo";

// Editable practical blocks are content-managed; these seed defaults each carry a
// visible "Last updated" and never hardcode timetables as permanent facts.
const BLOCKS: { title: string; body: string; updated: string }[] = [
  { title: "How to reach Mestia", body: "Mestia is reached by road from Zugdidi, Kutaisi or Tbilisi, and by a small domestic flight in season. Georgie can arrange private transfers — confirm current options when you inquire.", updated: "2026-07-14" },
  { title: "Road travel considerations", body: "Mountain roads are winding and conditions change with weather and season. Journey times vary; plan flexibility into your schedule.", updated: "2026-07-14" },
  { title: "Packing guidance", body: "Layered clothing, sturdy footwear, rain protection and sun protection are recommended year-round. Winter travel needs warmer gear.", updated: "2026-07-14" },
  { title: "Weather variability", body: "Mountain weather can shift quickly. Some routes are seasonal and may be affected by snow, rain or road conditions.", updated: "2026-07-14" },
  { title: "Mobile connectivity", body: "Coverage exists in towns but can be limited in remote valleys. Download offline maps before longer trips.", updated: "2026-07-14" },
  { title: "Currency and payments", body: "The local currency is the Georgian Lari (GEL). Carry some cash for villages where card payment may be unavailable.", updated: "2026-07-14" },
  { title: "Family & lower-activity travel", body: "Many experiences can be adapted for families and travelers who prefer less walking. Tell Georgie your pace.", updated: "2026-07-14" },
  { title: "Responsible tourism", body: "Please respect villages, churches and private property, and travel lightly in this fragile mountain environment.", updated: "2026-07-14" },
];

export function Component() {
  const { t } = useTranslation();
  const lang = useLang();
  return (
    <>
      <Seo title={`${t("nav.planTrip")} — Svaneti with Georgie`} description="Practical information for planning your trip to Mestia and Svaneti." canonicalPath={`/${lang}/plan-your-trip`} />
      <Section>
        <Container size="narrow">
          <SectionHeading as="h1" eyebrow="Before you go" title={t("nav.planTrip")} />
          <div className="space-y-6">
            {BLOCKS.map((b) => (
              <article key={b.title} className="rounded-2xl border border-border bg-surface/50 p-5">
                <h2 className="font-display text-xl">{b.title}</h2>
                <p className="mt-2 text-sm text-muted">{b.body}</p>
                <p className="mt-3 text-xs text-muted">{t("misc.lastUpdated")}: {b.updated}</p>
              </article>
            ))}
          </div>
        </Container>
      </Section>
    </>
  );
}
