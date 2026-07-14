import { useMemo, useState, useCallback, useEffect } from "react";
import { Chip, Spinner } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { useGallery } from "@/lib/queries";
import { useLang } from "@/lib/nav";
import { tt } from "@/i18n";
import { Container, Section, SectionHeading, MediaImage } from "@/components/primitives";
import { Seo } from "@/components/site/Seo";

export function Component() {
  const { t } = useTranslation();
  const lang = useLang();
  const { data, isLoading } = useGallery();
  const items = useMemo(() => data?.items ?? [], [data]);
  const [category, setCategory] = useState<string>("all");
  const [active, setActive] = useState<number | null>(null);

  const categories = useMemo(
    () => ["all", ...Array.from(new Set(items.map((i) => i.category).filter(Boolean) as string[]))],
    [items],
  );
  const filtered = category === "all" ? items : items.filter((i) => i.category === category);

  const close = useCallback(() => setActive(null), []);
  const next = useCallback(() => setActive((a) => (a === null ? a : (a + 1) % filtered.length)), [filtered.length]);
  const prev = useCallback(() => setActive((a) => (a === null ? a : (a - 1 + filtered.length) % filtered.length)), [filtered.length]);

  useEffect(() => {
    if (active === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      if (e.key === "ArrowRight") next();
      if (e.key === "ArrowLeft") prev();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, close, next, prev]);

  return (
    <>
      <Seo title={`${t("nav.gallery")} — Svaneti with Georgie`} description={t("home.fromTheGallery")} canonicalPath={`/${lang}/gallery`} />
      <Section>
        <Container size="wide">
          <SectionHeading as="h1" eyebrow="Svaneti" title={t("nav.gallery")} />
          {categories.length > 1 && (
            <div className="mb-6 flex flex-wrap gap-2">
              {categories.map((c) => (
                <button key={c} onClick={() => setCategory(c)} className="focus-visible:outline-none">
                  <Chip variant={category === c ? "primary" : "soft"} className="cursor-pointer capitalize">{c}</Chip>
                </button>
              ))}
            </div>
          )}

          {isLoading ? (
            <div className="grid min-h-64 place-items-center"><Spinner /></div>
          ) : (
            <div className="columns-2 gap-4 sm:columns-3 lg:columns-4 [&>*]:mb-4">
              {filtered.map((g, i) => (
                <button
                  key={g.id}
                  onClick={() => setActive(i)}
                  className="block w-full overflow-hidden rounded-xl focus-visible:outline focus-visible:outline-2 focus-visible:outline-copper"
                  aria-label={`Open image: ${tt(g.altText, lang) || g.location || "Svaneti"}`}
                >
                  <MediaImage url={g.thumbUrl ?? g.url} alt={tt(g.altText, lang) || g.location || "Svaneti"} ratio="" className="break-inside-avoid transition-transform hover:scale-[1.02]" />
                </button>
              ))}
            </div>
          )}
        </Container>
      </Section>

      {active !== null && filtered[active] && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Image viewer"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 p-4"
          onClick={close}
        >
          <button onClick={close} aria-label={t("actions.close")} className="absolute end-4 top-4 text-2xl text-white">✕</button>
          <button onClick={(e) => { e.stopPropagation(); prev(); }} aria-label="Previous" className="absolute start-4 text-3xl text-white/80 hover:text-white">‹</button>
          <figure onClick={(e) => e.stopPropagation()} className="max-h-[85vh] max-w-4xl">
            <img src={filtered[active].url} alt={tt(filtered[active].altText, lang) || "Svaneti"} className="max-h-[80vh] w-auto rounded-lg" />
            <figcaption className="mt-3 text-center text-sm text-white/80">
              {tt(filtered[active].caption, lang)}
              {filtered[active].location && <span> · {filtered[active].location}</span>}
              {filtered[active].credit && <span className="text-white/50"> · 📷 {filtered[active].credit}</span>}
            </figcaption>
          </figure>
          <button onClick={(e) => { e.stopPropagation(); next(); }} aria-label="Next" className="absolute end-4 text-3xl text-white/80 hover:text-white">›</button>
        </div>
      )}
    </>
  );
}
