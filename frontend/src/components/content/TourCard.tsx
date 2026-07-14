import { Card, Chip, Button } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { LangLink, useLang } from "@/lib/nav";
import { tt } from "@/i18n";
import { MediaImage } from "@/components/primitives";
import type { Tour } from "@/lib/types";

export function TourPrice({ tour }: { tour: Tour }) {
  const { t } = useTranslation();
  if (tour.priceDisplay === "amount" && tour.priceAmount) {
    return (
      <span className="font-semibold text-foreground">
        {t("labels.from")} {tour.currency ?? "GEL"} {tour.priceAmount}
      </span>
    );
  }
  return <span className="font-semibold text-copper">{t("actions.contactForPrice")}</span>;
}

export function TourCard({ tour }: { tour: Tour }) {
  const { t } = useTranslation();
  const lang = useLang();
  const duration =
    tour.durationDays
      ? `${tour.durationDays} ${t("labels.days")}`
      : tour.durationHours
        ? `${tour.durationHours} ${t("labels.hours")}`
        : undefined;

  return (
    <Card className="group flex h-full flex-col overflow-hidden">
      <div className="relative overflow-hidden">
        <MediaImage
          url={tour.coverUrl}
          alt={tt(tour.name, lang)}
          ratio="aspect-[3/2]"
          className="transition-transform duration-500 group-hover:scale-[1.04]"
        />
        <div className="absolute start-3 top-3 flex flex-wrap gap-1.5">
          {tour.tourType && (
            <Chip size="sm" variant="soft" className="bg-background/85 backdrop-blur">
              {t(`labels.${tour.tourType}`)}
            </Chip>
          )}
          {tour.winter && (
            <Chip size="sm" variant="soft" className="bg-glacier/85 text-white backdrop-blur">
              {t("labels.winter")}
            </Chip>
          )}
        </div>
      </div>
      <Card.Header>
        <Card.Title className="font-display text-lg leading-snug">
          {tt(tour.name, lang)}
        </Card.Title>
        {tour.startLocation && (
          <Card.Description className="text-copper">📍 {tour.startLocation}</Card.Description>
        )}
      </Card.Header>
      <Card.Content className="flex-1">
        <p className="line-clamp-3 text-sm text-muted">{tt(tour.shortDescription, lang)}</p>
        <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted">
          {duration && <span className="rounded-full bg-default/70 px-2.5 py-1">⏱ {duration}</span>}
          {tour.difficulty && (
            <span className="rounded-full bg-default/70 px-2.5 py-1 capitalize">
              ⛰ {t(`labels.difficulty`)}: {tour.difficulty}
            </span>
          )}
          {tour.familyFriendly && (
            <span className="rounded-full bg-default/70 px-2.5 py-1">👪 {t("labels.familyFriendly")}</span>
          )}
        </div>
      </Card.Content>
      <Card.Footer className="flex items-center justify-between">
        <TourPrice tour={tour} />
        <LangLink to={`/tours/${tour.slug}`}>
          <Button variant="secondary" size="sm">
            {t("actions.viewTour")}
          </Button>
        </LangLink>
      </Card.Footer>
    </Card>
  );
}
