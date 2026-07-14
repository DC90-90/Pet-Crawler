import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

export function Container({
  children,
  className = "",
  size = "default",
}: {
  children: ReactNode;
  className?: string;
  size?: "default" | "wide" | "narrow";
}) {
  const max =
    size === "wide" ? "max-w-7xl" : size === "narrow" ? "max-w-3xl" : "max-w-6xl";
  return <div className={`mx-auto w-full ${max} px-5 sm:px-8 ${className}`}>{children}</div>;
}

export function Section({
  children,
  className = "",
  id,
}: {
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section id={id} className={`py-14 sm:py-20 ${className}`}>
      {children}
    </section>
  );
}

export function SectionHeading({
  eyebrow,
  title,
  intro,
  align = "start",
  as: As = "h2",
}: {
  eyebrow?: string;
  title: string;
  intro?: string;
  align?: "start" | "center";
  as?: "h1" | "h2";
}) {
  return (
    <header className={`mb-8 sm:mb-12 ${align === "center" ? "text-center mx-auto max-w-2xl" : ""}`}>
      {eyebrow && (
        <p className="mb-2 text-sm font-semibold uppercase tracking-[0.18em] text-copper">
          {eyebrow}
        </p>
      )}
      <As className="font-display text-3xl sm:text-4xl font-medium text-foreground text-balance">
        {title}
      </As>
      {intro && <p className="mt-3 text-base sm:text-lg text-muted max-w-2xl">{intro}</p>}
      <div className="topo-divider mt-5 w-24" />
    </header>
  );
}

/** Gentle, reduced-motion-safe reveal wrapper. */
export function Reveal({
  children,
  delay = 0,
  className = "",
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  return (
    <div className={`reveal ${className}`} style={{ animationDelay: `${delay}ms` }}>
      {children}
    </div>
  );
}

/** Responsive image with a themed gradient fallback when no url is present. */
export function MediaImage({
  url,
  alt,
  className = "",
  ratio = "aspect-[4/3]",
  loading = "lazy",
}: {
  url?: string;
  alt: string;
  className?: string;
  ratio?: string;
  loading?: "lazy" | "eager";
}) {
  if (!url) {
    return (
      <div
        role="img"
        aria-label={alt}
        className={`${ratio} ${className} grid place-items-center overflow-hidden bg-gradient-to-br from-alpine-deep via-glacier-deep to-stone`}
      >
        <span className="px-3 text-center text-xs font-medium uppercase tracking-widest text-white/70">
          {alt}
        </span>
      </div>
    );
  }
  return (
    <img
      src={url}
      alt={alt}
      loading={loading}
      decoding="async"
      className={`${ratio} ${className} h-full w-full object-cover`}
    />
  );
}

/** Visible only when content is dev sample data. */
export function SampleFlag({ show }: { show?: boolean }) {
  const { t } = useTranslation();
  if (!show) return null;
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-warning/15 px-2.5 py-1 text-xs font-medium text-warning-foreground">
      ⚠ {t("misc.sampleContent")}
    </span>
  );
}

export function Stars({ rating }: { rating: number }) {
  return (
    <span className="inline-flex text-copper" aria-label={`${rating} out of 5`}>
      {Array.from({ length: 5 }).map((_, i) => (
        <span key={i} aria-hidden className={i < Math.round(rating) ? "" : "opacity-25"}>
          ★
        </span>
      ))}
    </span>
  );
}
