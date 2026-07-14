import { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { Modal, Button } from "@heroui/react";
import { usePopups } from "@/lib/queries";
import { useLang } from "@/lib/nav";
import { useDevice, getVisitorType } from "@/lib/useUi";
import { tt } from "@/i18n";
import { MediaImage } from "@/components/primitives";
import { eligibleByFrequency, popupKey } from "@/lib/popupFrequency";
import type { Popup } from "@/lib/types";

/** Enforces the popup's frequency rule using browser storage. */
function isEligible(p: Popup): boolean {
  const raw = localStorage.getItem(popupKey(p.id));
  return eligibleByFrequency(p, {
    lastShownAt: raw ? Number(raw) : null,
    shownThisSession: sessionStorage.getItem(popupKey(p.id)) !== null,
    now: Date.now(),
  });
}

function markShown(p: Popup) {
  localStorage.setItem(popupKey(p.id), String(Date.now()));
  sessionStorage.setItem(popupKey(p.id), "1");
}

export function PopupHost() {
  const location = useLocation();
  const lang = useLang();
  const device = useDevice();
  const visitor = useMemo(() => getVisitorType(), []);
  const { data } = usePopups(location.pathname, lang, device, visitor);
  const [active, setActive] = useState<Popup | null>(null);

  // Escape hatch: a stored preference (also used by e2e) disables all popups.
  const popupsDisabled =
    typeof localStorage !== "undefined" &&
    localStorage.getItem("svaneti-popups-disabled") === "1";

  // Pick the highest-priority eligible popup for this route.
  const candidate = useMemo(() => {
    if (popupsDisabled) return null;
    const list = (data?.items ?? [])
      .filter((p) => p.deviceTargets?.includes(device) ?? true)
      .filter((p) => p.audience === "all" || p.audience === visitor || !p.audience)
      .filter(isEligible)
      .sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0));
    return list[0] ?? null;
  }, [data, device, visitor, popupsDisabled]);

  // Trigger by delay, scroll depth, or exit intent.
  useEffect(() => {
    if (!candidate || active) return;
    let fired = false;
    const fire = () => {
      if (fired) return;
      fired = true;
      setActive(candidate);
      markShown(candidate);
    };
    const timer = candidate.delaySeconds
      ? window.setTimeout(fire, candidate.delaySeconds * 1000)
      : window.setTimeout(fire, 800);

    let onScroll: (() => void) | undefined;
    if (candidate.scrollDepthPercent) {
      onScroll = () => {
        const pct =
          (window.scrollY / (document.body.scrollHeight - window.innerHeight)) * 100;
        if (pct >= (candidate.scrollDepthPercent ?? 100)) fire();
      };
      window.addEventListener("scroll", onScroll, { passive: true });
    }
    let onLeave: ((e: MouseEvent) => void) | undefined;
    if (candidate.exitIntent && device === "desktop") {
      onLeave = (e: MouseEvent) => {
        if (e.clientY <= 0) fire();
      };
      document.addEventListener("mouseout", onLeave);
    }
    return () => {
      window.clearTimeout(timer);
      if (onScroll) window.removeEventListener("scroll", onScroll);
      if (onLeave) document.removeEventListener("mouseout", onLeave);
    };
  }, [candidate, active, device]);

  if (!active) return null;

  return (
    <Modal isOpen={!!active} onOpenChange={(open) => !open && setActive(null)}>
      <Modal.Backdrop isDismissable={active.dismissible !== false}>
        <Modal.Container>
          <Modal.Dialog>
            {active.dismissible !== false && <Modal.CloseTrigger />}
            {active.mediaUrl && (
              <MediaImage url={active.mediaUrl} alt={tt(active.title, lang)} ratio="aspect-[16/9]" />
            )}
            <Modal.Header>
              <Modal.Heading>{tt(active.title, lang)}</Modal.Heading>
            </Modal.Header>
            <Modal.Body>
              <p className="text-muted">{tt(active.body, lang)}</p>
            </Modal.Body>
            <Modal.Footer>
              {active.cta && (
                <a href={active.cta.href}>
                  <Button variant="primary">{tt(active.cta.label, lang)}</Button>
                </a>
              )}
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
