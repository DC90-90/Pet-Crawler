import { useParams } from "react-router-dom";
import { Button, Chip, Spinner } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { useTour } from "@/lib/queries";
import { LangLink, useLang } from "@/lib/nav";
import { tt } from "@/i18n";
import { Container, Section, MediaImage, SampleFlag } from "@/components/primitives";
import { TourPrice } from "@/components/content/TourCard";
import { Seo } from "@/components/site/Seo";

export function Component() {
  const { slug } = useParams();
  const lang = useLang();
  const { t } = useTranslation();
  const { data: tour, isLoading, isError } = useTour(slug ?? "");

  if (isLoading)
    return (
      <div className="grid min-h-[60vh] place-items-center">
        <Spinner />
      </div>
    );
  if (isError || !tour)
    return (
      <Container className="py-24 text-center">
        <p className="text-muted">{t("misc.notFound")}</p>
        <LangLink to="/tours" className="mt-4 inline-block text-copper underline">
          {t("nav.tours")}
        </LangLink>
      </Container>
    );

  const meta: [string, string | undefined][] = [
    [t("labels.duration"), tour.durationDays ? `${tour.durationDays} ${t("labels.days")}` : tour.durationHours ? `${tour.durationHours} ${t("labels.hours")}` : undefined],
    [t("labels.difficulty"), tour.difficulty],
    [t("labels.type"), tour.tourType ? t(`labels.${tour.tourType}`) : undefined],
    [t("labels.location"), tour.startLocation],
    ["Max altitude", tour.maxAltitudeM ? `${tour.maxAltitudeM} m` : undefined],
  ];

  return (
    <>
      <Seo
        title={`${tt(tour.name, lang)} — Svaneti with Georgie`}
        description={tt(tour.shortDescription, lang)}
        ogImage={tour.coverUrl}
        canonicalPath={`/${lang}/tours/${tour.slug}`}
        jsonLd={{
          "@context": "https://schema.org",
          "@type": "TouristTrip",
          name: tt(tour.name, lang),
          description: tt(tour.shortDescription, lang),
          touristType: tour.tourType,
        }}
      />

      {/* Hero */}
      <section className="relative isolate text-white">
        <div className="absolute inset-0 -z-10">
          <MediaImage url={tour.coverUrl} alt={tt(tour.name, lang)} ratio="h-full" loading="eager" />
          <div className="absolute inset-0 bg-black/45" />
        </div>
        <Container className="flex min-h-[52vh] flex-col justify-end py-16">
          <nav aria-label="Breadcrumb" className="mb-3 text-sm text-white/75">
            <LangLink to="/tours" className="hover:underline">{t("nav.tours")}</LangLink>
            <span className="mx-2">/</span>
            <span>{tt(tour.name, lang)}</span>
          </nav>
          <h1 className="max-w-3xl font-display text-4xl font-medium sm:text-5xl">{tt(tour.name, lang)}</h1>
          <div className="mt-4 flex flex-wrap gap-2">
            {tour.seasons?.map((s) => (
              <Chip key={s} size="sm" variant="soft" className="bg-white/15 text-white capitalize">{s}</Chip>
            ))}
          </div>
        </Container>
      </section>

      <Section>
        <Container>
          <div className="grid gap-12 lg:grid-cols-[1fr_340px]">
            <div>
              <SampleFlag show={tour.verificationStatus === "needs_verification"} />
              <p className="mt-3 text-lg text-foreground/90">{tt(tour.shortDescription, lang)}</p>
              {tour.fullDescription && (
                <div className="prose-alpine mt-6" dangerouslySetInnerHTML={{ __html: tt(tour.fullDescription, lang) }} />
              )}

              {tour.itinerary && tour.itinerary.length > 0 && (
                <div className="mt-10">
                  <h2 className="font-display text-2xl">Itinerary</h2>
                  <ol className="mt-4 space-y-4 border-s-2 border-copper/40 ps-5">
                    {tour.itinerary.map((step, i) => (
                      <li key={i} className="relative">
                        <span className="absolute -start-[27px] top-1 grid h-5 w-5 place-items-center rounded-full bg-copper text-xs text-white">{i + 1}</span>
                        <p className="font-semibold">{tt(step.title, lang)}</p>
                        <p className="text-sm text-muted">{tt(step.body, lang)}</p>
                      </li>
                    ))}
                  </ol>
                </div>
              )}

              <div className="mt-10 grid gap-8 sm:grid-cols-2">
                {tour.inclusions && tour.inclusions.length > 0 && (
                  <div>
                    <h3 className="font-semibold text-success">Included</h3>
                    <ul className="mt-2 space-y-1 text-sm text-muted">
                      {tour.inclusions.map((x, i) => <li key={i}>✓ {tt(x, lang)}</li>)}
                    </ul>
                  </div>
                )}
                {tour.exclusions && tour.exclusions.length > 0 && (
                  <div>
                    <h3 className="font-semibold text-danger">Not included</h3>
                    <ul className="mt-2 space-y-1 text-sm text-muted">
                      {tour.exclusions.map((x, i) => <li key={i}>✕ {tt(x, lang)}</li>)}
                    </ul>
                  </div>
                )}
              </div>

              {tour.whatToBring && tour.whatToBring.length > 0 && (
                <div className="mt-8">
                  <h3 className="font-semibold">What to bring</h3>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {tour.whatToBring.map((x, i) => <Chip key={i} size="sm" variant="soft">{tt(x, lang)}</Chip>)}
                  </div>
                </div>
              )}

              {tour.safetyNotes && tt(tour.safetyNotes, lang) && (
                <div className="mt-8 rounded-xl border border-warning/40 bg-warning/10 p-4 text-sm">
                  <strong>Safety:</strong> {tt(tour.safetyNotes, lang)}
                </div>
              )}
            </div>

            {/* Sticky booking card */}
            <aside className="lg:sticky lg:top-24 lg:self-start">
              <div className="rounded-2xl border border-border bg-surface/70 p-6 shadow-sm">
                <div className="text-2xl"><TourPrice tour={tour} /></div>
                <dl className="mt-4 space-y-2 text-sm">
                  {meta.filter(([, v]) => v).map(([k, v]) => (
                    <div key={k} className="flex justify-between gap-4 border-b border-border/60 pb-2">
                      <dt className="text-muted">{k}</dt>
                      <dd className="font-medium capitalize">{v}</dd>
                    </div>
                  ))}
                </dl>
                <LangLink to={`/inquiry?tour=${tour.slug}`} className="mt-5 block">
                  <Button variant="primary" className="w-full">{t("actions.sendInquiry")}</Button>
                </LangLink>
                <p className="mt-3 text-center text-xs text-muted">{t("home.inquiryBody")}</p>
              </div>
            </aside>
          </div>

          {tour.galleryUrls && tour.galleryUrls.length > 0 && (
            <div className="mt-14">
              <h2 className="font-display text-2xl">Gallery</h2>
              <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                {tour.galleryUrls.map((u, i) => (
                  <MediaImage key={i} url={u} alt={`${tt(tour.name, lang)} ${i + 1}`} ratio="aspect-square" className="rounded-xl" />
                ))}
              </div>
            </div>
          )}
        </Container>
      </Section>
    </>
  );
}
