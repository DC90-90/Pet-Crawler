import { test, expect } from "@playwright/test";

// Admin flows run against a single mock-DB backend process seeded with a dev owner
// (owner@example.com / ChangeMe!Now123). See scripts/e2e.sh.

const EMAIL = process.env.ADMIN_SEED_EMAIL || "owner@example.com";
const PASSWORD = process.env.ADMIN_SEED_PASSWORD || "ChangeMe!Now123";

async function login(page: import("@playwright/test").Page) {
  await page.goto("/admin/login");
  await page.getByLabel(/email/i).fill(EMAIL);
  await page.getByLabel(/password/i).fill(PASSWORD);
  await page.getByRole("button", { name: /log ?in|sign ?in/i }).click();
  await expect(page).toHaveURL(/\/admin(\/)?$/);
}

test("owner can log in and see the dashboard", async ({ page }) => {
  await login(page);
  await expect(page.getByText(/overview|dashboard/i).first()).toBeVisible();
});

test("owner can reach the banners module", async ({ page }) => {
  await login(page);
  await page.goto("/admin/banners");
  await expect(page.getByRole("heading", { name: /banners/i })).toBeVisible();
});

test("draft tour hidden from public, published tour visible", async ({ page }) => {
  // Backed by the seed: 9 published + 1 draft.
  const published = await page.request.get(
    "http://localhost:8000/api/public/tours/ushguli-shkhara-private-day-journey",
  );
  expect(published.status()).toBe(200);
  const draft = await page.request.get(
    "http://localhost:8000/api/public/tours/custom-svaneti-itinerary",
  );
  expect(draft.status()).toBe(404);
});
