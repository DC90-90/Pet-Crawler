import { describe, it, expect } from "vitest";
import { eligibleByFrequency } from "@/lib/popupFrequency";

const DAY = 24 * 3600_000;
const now = 1_000 * DAY; // fixed reference

describe("popup frequency rules", () => {
  it("every_visit always shows", () => {
    expect(eligibleByFrequency({ id: "a", frequency: "every_visit" }, { lastShownAt: now, shownThisSession: true, now })).toBe(true);
  });

  it("once_ever shows only when never shown", () => {
    expect(eligibleByFrequency({ id: "a", frequency: "once_ever" }, { lastShownAt: null, shownThisSession: false, now })).toBe(true);
    expect(eligibleByFrequency({ id: "a", frequency: "once_ever" }, { lastShownAt: now - 999 * DAY, shownThisSession: false, now })).toBe(false);
  });

  it("once_session respects session flag", () => {
    expect(eligibleByFrequency({ id: "a", frequency: "once_session" }, { lastShownAt: null, shownThisSession: false, now })).toBe(true);
    expect(eligibleByFrequency({ id: "a", frequency: "once_session" }, { lastShownAt: null, shownThisSession: true, now })).toBe(false);
  });

  it("once_day shows again after 24h", () => {
    expect(eligibleByFrequency({ id: "a", frequency: "once_day" }, { lastShownAt: now - 2 * DAY, shownThisSession: true, now })).toBe(true);
    expect(eligibleByFrequency({ id: "a", frequency: "once_day" }, { lastShownAt: now - 3600_000, shownThisSession: false, now })).toBe(false);
  });

  it("custom_days honors frequencyDays", () => {
    expect(eligibleByFrequency({ id: "a", frequency: "custom_days", frequencyDays: 5 }, { lastShownAt: now - 6 * DAY, shownThisSession: false, now })).toBe(true);
    expect(eligibleByFrequency({ id: "a", frequency: "custom_days", frequencyDays: 5 }, { lastShownAt: now - 2 * DAY, shownThisSession: false, now })).toBe(false);
  });
});
