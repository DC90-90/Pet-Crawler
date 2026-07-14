import { Button, Card, Chip, Tabs } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { LangLink, useLang } from "@/lib/nav";
import { tt } from "@/i18n";
import {
  useTours,
  useDestinations,
  useOffers,
  useReviews,
  useFaqs,
  useGallery,
  useVideos,
} from "@/lib/queries";
import { Container, Section, SectionHeading, Reveal, MediaImage, Stars, SampleFlag } from "@/components/primitives";
import { TourCard } from "./TourCard";
import { SvanetiMap } from "./SvanetiMap";
import type { PageSection } from "@/lib/types";

/* eslint-disable @typescript-eslint/no-explicit-any */
type D = Record<string, any>;

function Hero({ data }: { data: D }) {
  const lang = useLang();
  const { t } = useTranslation();
  const overlay = data.overlayIntensity ?? 0.45;
  return (
    <section className="relative isolate overflow-hidden">
      <div className="absolute inset-0 -z-10">
        <MediaImage
          url={data.mediaUrl}
          alt=""
          ratio="h-full"
          loading="eager"
          className="h-full w-full"
        />
        <div className="absolute inset-0" style={{ background: `rgba(20,28,22,${overlay})` }} />
      </div>
      <Container className="flex min-h-[72vh] flex-col justify-center py-24 text-white">
        <Reveal>
          {data.badge && (
            <Chip variant="soft" className="mb-5 w-fit bg-copper text-white">
              {tt(data.badge, lang)}
            </Chip>
          )}
          <h1 className="max-w-3xl font-display text-4xl font-medium leading-[1.05] text-balance sm:text-6xl">
            {tt(data.heading ?? data.title, lang) || "Svaneti, Guided by a Local"}
          </h1>
          <p className="mt-5 max-w-xl text-lg text-white/85">
            {tt(data.subheading ?? data.subtitle, lang) ||
              "Discover Mestia, Ushguli and the Caucasus mountains through local stories, flexible private journeys and unforgettable landscapes."}
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <LangLink to={data.primaryCta?.href ?? data.cta?.href ?? "/tours"}>
              <Button variant="primary" size="lg">
                {tt(data.primaryCta?.label ?? data.cta?.label, lang) || t("actions.exploreTours")}
              </Button>
            </LangLink>
            <LangLink to={data.secondaryCta?.href ?? "/inquiry"}>
              <Button variant="secondary" size="lg" className="bg-white/10 text-white backdrop-blur">
                {tt(data.secondaryCta?.label, lang) || t("actions.chatWithGeorgie")}
              </Button>
            </LangLink>
          </div>
        </Reveal>
      </Container>
    </section>
  );
}

function TrustStrip({ data }: { data: D }) {
  const lang = useLang();
  const points: D[] = data.points ?? [];
  return (
    <div className="border-y border-border bg-surface/50">
      <Container className="grid gap-6 py-8 sm:grid-cols-2 lg:grid-cols-4">
        {points.map((p, i) => (
          <div key={i} className="flex items-start gap-3">
            <span aria-hidden className="text-2xl">{p.icon ?? "⛰"}</span>
            <div>
              <p className="font-semibold">{tt(p.title, lang)}</p>
              {p.text && <p className="text-sm text-muted">{tt(p.text, lang)}</p>}
            </div>
          </div>
        ))}
      </Container>
    </div>
  );
}

function TourGrid({ data }: { data: D }) {
  const { t } = useTranslation();
  const { data: tours } = useTours({ featured: data.featuredOnly ? true : undefined, pageSize: data.limit ?? 6 });
  const items = (tours?.items ?? []).slice(0, data.limit ?? 6);
  return (
    <Section>
      <Container>
        <SectionHeading eyebrow={tt(data.eyebrow, "en")} title={tt(data.title, "en") || t("home.featuredTours")} intro={tt(data.intro, "en")} />
        {items.length === 0 ? (
          <p className="text-muted">{t("misc.empty")}</p>
        ) : (
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((tour, i) => (
              <Reveal key={tour.id} delay={i * 60}>
                <TourCard tour={tour} />
              </Reveal>
            ))}
          </div>
        )}
        <div className="mt-8">
          <LangLink to="/tours">
            <Button variant="tertiary">{t("actions.viewAll")} →</Button>
          </LangLink>
        </div>
      </Container>
    </Section>
  );
}

function DestinationGrid({ data }: { data: D }) {
  const lang = useLang();
  const { t } = useTranslation();
  const { data: dests } = useDestinations();
  const items = (dests?.items ?? []).slice(0, data.limit ?? 8);
  return (
    <Section className="bg-surface/40">
      <Container>
        <SectionHeading eyebrow={tt(data.eyebrow, lang)} title={tt(data.title, lang) || t("home.signatureDestinations")} intro={tt(data.intro, lang)} />
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {items.map((d, i) => (
            <Reveal key={d.id} delay={i * 50}>
              <LangLink to={`/destinations/${d.slug}`} className="group block">
                <Card className="overflow-hidden">
                  <div className="relative">
                    <MediaImage url={d.coverUrl} alt={tt(d.name, lang)} ratio="aspect-[4/5]" className="transition-transform duration-500 group-hover:scale-105" />
                    <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent p-4">
                      <p className="font-display text-lg text-white">{tt(d.name, lang)}</p>
                      {d.altitudeM && <p className="text-xs text-white/75">{d.altitudeM} m</p>}
                    </div>
                  </div>
                </Card>
              </LangLink>
            </Reveal>
          ))}
        </div>
      </Container>
    </Section>
  );
}

function SeasonalCards({ data }: { data: D }) {
  const lang = useLang();
  const { t } = useTranslation();
  const seasons: D[] = data.seasons ?? [
    { key: "spring", title: { en: "Spring" } },
    { key: "summer", title: { en: "Summer" } },
    { key: "autumn", title: { en: "Autumn" } },
    { key: "winter", title: { en: "Winter" } },
  ];
  return (
    <Section>
      <Container>
        <SectionHeading title={tt(data.title, lang) || t("home.seasonal")} intro={tt(data.intro, lang)} />
        <Tabs defaultSelectedKey={seasons[0]?.key}>
          <Tabs.ListContainer>
            <Tabs.List aria-label={t("home.seasonal")}>
              {seasons.map((s) => (
                <Tabs.Tab key={s.key} id={s.key}>
                  {tt(s.title, lang)}
                  <Tabs.Indicator />
                </Tabs.Tab>
              ))}
            </Tabs.List>
          </Tabs.ListContainer>
          {seasons.map((s) => (
            <Tabs.Panel key={s.key} id={s.key}>
              <div className="grid gap-4 pt-6 sm:grid-cols-3">
                {(s.experiences ?? [{ title: s.title, text: { en: "Seasonal experiences to be confirmed by the guide." } }]).map(
                  (e: D, i: number) => (
                    <Card key={i}>
                      <Card.Header>
                        <Card.Title>{tt(e.title, lang)}</Card.Title>
                      </Card.Header>
                      <Card.Content>
                        <p className="text-sm text-muted">{tt(e.text, lang)}</p>
                      </Card.Content>
                    </Card>
                  ),
                )}
              </div>
            </Tabs.Panel>
          ))}
        </Tabs>
      </Container>
    </Section>
  );
}

function OffersSection() {
  const lang = useLang();
  const { t } = useTranslation();
  const { data } = useOffers();
  const items = data?.items ?? [];
  if (items.length === 0) return null;
  return (
    <Section>
      <Container>
        <SectionHeading title={t("nav.offers")} />
        <div className="grid gap-6 md:grid-cols-2">
          {items.map((o) => (
            <Card key={o.id} className="border-copper/30">
              <Card.Header>
                <Card.Title className="flex items-center gap-2">
                  {tt(o.title, lang)}
                  {o.code && <Chip size="sm" variant="soft" className="bg-copper/15 text-copper">{o.code}</Chip>}
                </Card.Title>
              </Card.Header>
              <Card.Content>
                <p className="text-sm text-muted">{tt(o.description, lang)}</p>
              </Card.Content>
              {o.cta && (
                <Card.Footer>
                  <a href={o.cta.href}><Button variant="secondary" size="sm">{tt(o.cta.label, lang)}</Button></a>
                </Card.Footer>
              )}
            </Card>
          ))}
        </div>
      </Container>
    </Section>
  );
}

function Testimonials() {
  const { t } = useTranslation();
  const { data } = useReviews();
  const items = (data?.items ?? []).slice(0, 3);
  if (items.length === 0) return null;
  return (
    <Section className="bg-surface/40">
      <Container>
        <SectionHeading title={t("nav.reviews")} />
        <div className="grid gap-6 md:grid-cols-3">
          {items.map((r) => (
            <Card key={r.id}>
              <Card.Content className="pt-6">
                <div className="mb-2 flex items-center justify-between">
                  <Stars rating={r.rating} />
                  <SampleFlag show={r.isSample} />
                </div>
                <p className="text-sm text-foreground/90">“{r.text}”</p>
                <p className="mt-3 text-sm font-semibold">
                  {r.reviewerName}
                  {r.country && <span className="font-normal text-muted"> · {r.country}</span>}
                </p>
              </Card.Content>
            </Card>
          ))}
        </div>
      </Container>
    </Section>
  );
}

function FaqSection() {
  const lang = useLang();
  const { data } = useFaqs();
  const items = (data?.items ?? []).slice(0, 6);
  if (items.length === 0) return null;
  return (
    <Section>
      <Container size="narrow">
        <SectionHeading title="FAQ" align="center" />
        <div className="divide-y divide-border">
          {items.map((f) => (
            <details key={f.id} className="group py-4">
              <summary className="cursor-pointer list-none font-medium marker:content-none">
                <span className="inline-flex w-full items-center justify-between gap-4">
                  {tt(f.question, lang)}
                  <span aria-hidden className="text-copper transition-transform group-open:rotate-45">+</span>
                </span>
              </summary>
              <p className="mt-2 text-sm text-muted">{tt(f.answer, lang)}</p>
            </details>
          ))}
        </div>
      </Container>
    </Section>
  );
}

function GallerySection() {
  const lang = useLang();
  const { t } = useTranslation();
  const { data } = useGallery();
  const items = (data?.items ?? []).slice(0, 8);
  if (items.length === 0) return null;
  return (
    <Section>
      <Container size="wide">
        <SectionHeading title={t("home.fromTheGallery")} />
        <div className="columns-2 gap-4 sm:columns-3 lg:columns-4 [&>*]:mb-4">
          {items.map((g) => (
            <MediaImage key={g.id} url={g.thumbUrl ?? g.url} alt={tt(g.altText, lang) || g.location || "Svaneti"} ratio="" className="break-inside-avoid rounded-xl" />
          ))}
        </div>
      </Container>
    </Section>
  );
}

function VideoSection() {
  const lang = useLang();
  const { t } = useTranslation();
  const { data } = useVideos();
  const featured = (data?.items ?? []).find((v) => v.featured) ?? data?.items?.[0];
  if (!featured) return null;
  return (
    <Section className="bg-alpine-deep text-white">
      <Container>
        <SectionHeading title={t("home.storiesInMotion")} />
        <div className="overflow-hidden rounded-2xl">
          {featured.kind === "youtube" && featured.externalUrl ? (
            <div className="aspect-video">
              <iframe
                className="h-full w-full"
                src={featured.externalUrl.replace("watch?v=", "embed/")}
                title={tt(featured.title, lang)}
                allow="accelerometer; encrypted-media; picture-in-picture"
                allowFullScreen
              />
            </div>
          ) : (
            <MediaImage url={featured.posterUrl} alt={tt(featured.title, lang)} ratio="aspect-video" />
          )}
        </div>
      </Container>
    </Section>
  );
}

function MapSection({ data }: { data: D }) {
  const lang = useLang();
  return (
    <Section>
      <Container>
        <SectionHeading title={tt(data.title, lang) || "Where we travel"} intro={tt(data.intro, lang)} />
        <SvanetiMap />
      </Container>
    </Section>
  );
}

function RichText({ data }: { data: D }) {
  const lang = useLang();
  return (
    <Section>
      <Container size="narrow">
        <div className="prose-alpine" dangerouslySetInnerHTML={{ __html: tt(data.html, lang) }} />
      </Container>
    </Section>
  );
}

function Split({ data }: { data: D }) {
  const lang = useLang();
  const reverse = data.mediaSide === "end";
  return (
    <Section>
      <Container>
        <div className={`grid items-center gap-10 lg:grid-cols-2 ${reverse ? "lg:[&>*:first-child]:order-2" : ""}`}>
          <MediaImage url={data.mediaUrl} alt={tt(data.title, lang)} ratio="aspect-[4/3]" className="rounded-2xl" />
          <div>
            {data.eyebrow && <p className="mb-2 text-sm font-semibold uppercase tracking-widest text-copper">{tt(data.eyebrow, lang)}</p>}
            <h2 className="font-display text-3xl font-medium">{tt(data.title, lang)}</h2>
            <div className="prose-alpine mt-4" dangerouslySetInnerHTML={{ __html: tt(data.body, lang) }} />
            {data.cta && (
              <LangLink to={data.cta.href} className="mt-6 inline-block">
                <Button variant="secondary">{tt(data.cta.label, lang)}</Button>
              </LangLink>
            )}
          </div>
        </div>
      </Container>
    </Section>
  );
}

function CtaSection({ data }: { data: D }) {
  const lang = useLang();
  const { t } = useTranslation();
  return (
    <Section>
      <Container>
        <div className="relative overflow-hidden rounded-3xl bg-alpine-deep px-8 py-14 text-center text-white">
          <div className="topo-divider mx-auto mb-6 w-24 opacity-60" />
          <h2 className="mx-auto max-w-2xl font-display text-3xl font-medium sm:text-4xl">
            {tt(data.title, lang) || t("home.inquiryTitle")}
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-white/85">
            {tt(data.body, lang) || t("home.inquiryBody")}
          </p>
          <LangLink to={data.cta?.href ?? "/inquiry"} className="mt-8 inline-block">
            <Button variant="primary" size="lg" className="bg-copper">
              {tt(data.cta?.label, lang) || t("actions.sendInquiry")}
            </Button>
          </LangLink>
        </div>
      </Container>
    </Section>
  );
}

export function SectionRenderer({ section }: { section: PageSection }) {
  if (section.hidden) return null;
  const d = section.data ?? {};
  switch (section.type) {
    case "hero": return <Hero data={d} />;
    case "stats":
    case "logoStrip":
    case "announcement": return <TrustStrip data={d} />;
    case "tourGrid": return <TourGrid data={d} />;
    case "destinationGrid": return <DestinationGrid data={d} />;
    case "seasonalCards": return <SeasonalCards data={d} />;
    case "offers": return <OffersSection />;
    case "testimonials": return <Testimonials />;
    case "faq": return <FaqSection />;
    case "gallery": return <GallerySection />;
    case "video": return <VideoSection />;
    case "map": return <MapSection data={d} />;
    case "richtext": return <RichText data={d} />;
    case "split": return <Split data={d} />;
    case "cta":
    case "contactForm": return <CtaSection data={d} />;
    default: return null;
  }
}
