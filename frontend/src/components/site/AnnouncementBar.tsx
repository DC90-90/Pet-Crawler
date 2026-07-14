import { useState } from "react";
import { useLocation } from "react-router-dom";
import { useBanners } from "@/lib/queries";
import { useLang } from "@/lib/nav";
import { useDevice } from "@/lib/useUi";
import { tt } from "@/i18n";

export function AnnouncementBar() {
  const location = useLocation();
  const lang = useLang();
  const device = useDevice();
  const [dismissed, setDismissed] = useState(false);
  const { data } = useBanners(location.pathname, lang, device);

  const banner = data?.items.find((b) => b.placement === "announcement");
  if (!banner || dismissed) return null;

  return (
    <div className="relative bg-alpine-deep text-white">
      <div className="mx-auto flex max-w-6xl items-center justify-center gap-3 px-10 py-2.5 text-center text-sm">
        <p className="font-medium">
          {tt(banner.title, lang)}
          {banner.cta && (
            <a href={banner.cta.href} className="ms-2 font-semibold text-copper-soft underline">
              {tt(banner.cta.label, lang)}
            </a>
          )}
        </p>
        <button
          type="button"
          onClick={() => setDismissed(true)}
          aria-label="Dismiss announcement"
          className="absolute end-3 top-1/2 -translate-y-1/2 rounded p-1 text-white/70 hover:text-white"
        >
          ✕
        </button>
      </div>
    </div>
  );
}
