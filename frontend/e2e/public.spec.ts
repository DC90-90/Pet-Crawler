import { test, expect } from "@playwright/test";

// These cover the public/anonymous subset of the master-prompt e2e scenarios.
// Run with the backend on :8000 (USE_MOCK_DB=true is fine) and the frontend on :5173.

// Suppress the marketing popup so its modal backdrop doesn't intercept clicks mid-test.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try {
      localStorage.setItem("svaneti-popups-disabled", "1");
    } catch {
      /* ignore */
    }
  });
});

test("homepage renders hero and redirects root to a language", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/(en|ka|ar)$/);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
});

test("SEO: public pages expose a meaningful title", async ({ page }) => {
  await page.goto("/en");
  await expect(page).toHaveTitle(/Svaneti with Georgie/i);
});

test("published tour is public; a draft slug is not", async ({ page }) => {
  await page.goto("/en/tours");
  await expect(page.getByRole("heading", { level: 1, name: /Tours/i })).toBeVisible();
  // A published seed tour resolves:
  const res = await page.request.get(
    "http://localhost:8000/api/public/tours/ushguli-shkhara-private-day-journey",
  );
  expect(res.status()).toBe(200);
  // The seeded draft tour must 404 on the public API:
  const draft = await page.request.get(
    "http://localhost:8000/api/public/tours/custom-svaneti-itinerary",
  );
  expect(draft.status()).toBe(404);
});

test("Arabic switches the interface to RTL", async ({ page }) => {
  await page.goto("/ar");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.locator("html")).toHaveAttribute("lang", "ar");
});

test("unauthorized visitor cannot open the dashboard", async ({ page }) => {
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/admin\/login/);
});

test("visitor can submit an inquiry", async ({ page }) => {
  await page.goto("/en/inquiry");
  await page.getByLabel(/Full name/i).fill("Test Traveler");
  await page.getByLabel(/Email/i).first().fill("traveler@example.com");
  await page.getByLabel(/message/i).fill("We have five days in August and enjoy moderate hikes.");
  await page.getByText(/agree to be contacted/i).click();
  // Scope to the form's submit button (the header also has a "Send inquiry" link-button).
  await page.locator("form").getByRole("button", { name: /send inquiry/i }).click();
  await expect(page.getByText(/reached Georgie|Thank you/i)).toBeVisible();
});
