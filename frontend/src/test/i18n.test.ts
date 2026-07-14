import { describe, it, expect } from "vitest";
import { tt, isRtl, SUPPORTED_LANGS } from "@/i18n";

describe("localization helpers", () => {
  it("picks the requested language with English fallback", () => {
    const value = { en: "Hello", ka: "გამარჯობა", ar: "مرحبا" };
    expect(tt(value, "en")).toBe("Hello");
    expect(tt(value, "ka")).toBe("გამარჯობა");
    expect(tt(value, "ar")).toBe("مرحبا");
    expect(tt({ en: "Only EN" }, "ka")).toBe("Only EN");
    expect(tt(undefined, "en")).toBe("");
  });

  it("flags Arabic as RTL and others as LTR", () => {
    expect(isRtl("ar")).toBe(true);
    expect(isRtl("ar-SA")).toBe(true);
    expect(isRtl("en")).toBe(false);
    expect(isRtl("ka")).toBe(false);
  });

  it("supports the three launch languages", () => {
    expect(SUPPORTED_LANGS).toEqual(["en", "ka", "ar"]);
  });
});
