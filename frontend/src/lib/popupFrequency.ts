import type { Popup } from "./types";

export const popupKey = (id: string) => `svaneti-popup-${id}`;

/**
 * Decide whether a popup may show now, given its frequency rule and prior views.
 * Pure + injectable storage so it is unit-testable without a browser.
 */
export function eligibleByFrequency(
  p: Pick<Popup, "id" | "frequency" | "frequencyDays">,
  opts: {
    lastShownAt: number | null;
    shownThisSession: boolean;
    now: number;
  },
): boolean {
  const { lastShownAt, shownThisSession, now } = opts;
  switch (p.frequency) {
    case "every_visit":
      return true;
    case "once_session":
      return !shownThisSession;
    case "once_ever":
      return lastShownAt === null;
    case "once_day":
      return lastShownAt === null || now - lastShownAt > 24 * 3600_000;
    case "custom_days":
      return lastShownAt === null || now - lastShownAt > (p.frequencyDays ?? 7) * 24 * 3600_000;
    default:
      return lastShownAt === null;
  }
}
