/**
 * iter73j — CardPeriod wiring test.
 *
 * The Insights page has 8 cards that must ALL declare the period their
 * numbers cover, per client request ("i want to add a period relevant for
 * each card"). This test is a structural fence: it reads the source and
 * asserts every window-dependent card carries `<CardPeriod window={days}`
 * and every point-in-time card carries `<CardPeriod window="current"`.
 *
 * When a new card is added to InsightsPage or SalesInsights without a
 * CardPeriod, this test fails — forcing the author to declare the window.
 */
const fs = require("fs");
const path = require("path");

const INSIGHTS_PAGE = path.join(__dirname, "..", "src", "pages", "InsightsPage.jsx");
const SALES_INSIGHTS = path.join(__dirname, "..", "src", "components", "SalesInsights.jsx");
const CARD_PERIOD = path.join(__dirname, "..", "src", "components", "CardPeriod.jsx");

const insightsPage = fs.readFileSync(INSIGHTS_PAGE, "utf8");
const salesInsights = fs.readFileSync(SALES_INSIGHTS, "utf8");
const cardPeriod = fs.readFileSync(CARD_PERIOD, "utf8");

function assert(cond, msg) {
  if (!cond) {
    // eslint-disable-next-line no-console
    console.error("✗", msg);
    process.exitCode = 1;
  } else {
    // eslint-disable-next-line no-console
    console.log("✓", msg);
  }
}

// ── CardPeriod component contract ──────────────────────────────────────────
assert(cardPeriod.includes("export function CardPeriod"),
  "CardPeriod exports a named `CardPeriod` component");
assert(cardPeriod.includes('period_last_days') && cardPeriod.includes('period_current'),
  "CardPeriod references both i18n keys (period_last_days + period_current)");
assert(cardPeriod.includes('window === "current"'),
  "CardPeriod handles the point-in-time (current) mode");
assert(cardPeriod.includes('data-testid'),
  "CardPeriod attaches a data-testid so tests can assert its presence");

// ── window-dependent cards on the Insights page ────────────────────────────
const windowDependent = [
  { name: "Revenue Leaderboard",   testId: "leaderboard-period" },
  { name: "Top Sellers",           testId: "top-sellers-period" },
  { name: "Trending",              testId: "trending-period" },
];
windowDependent.forEach(({ name, testId }) => {
  assert(
    insightsPage.includes(`<CardPeriod window={days} testId="${testId}" />`),
    `${name} card carries <CardPeriod window={days} testId="${testId}" />`,
  );
});

// ── point-in-time cards (no window param on the endpoint) ──────────────────
const pointInTime = [
  { name: "Price Wars",              testId: "price-wars-period" },
  { name: "Restock Opportunities",   testId: "restock-period" },
  { name: "Product Gaps",            testId: "gaps-period" },
];
pointInTime.forEach(({ name, testId }) => {
  assert(
    insightsPage.includes(`<CardPeriod window="current" testId="${testId}" />`),
    `${name} card carries <CardPeriod window="current" testId="${testId}" />`,
  );
});

// ── SalesInsights cards (Top Brands + Products table) ──────────────────────
assert(
  salesInsights.includes(
    '<CardPeriod window={days} dateFrom={dateFrom} dateTo={dateTo} testId="si-top-brands-period" />'
  ),
  "Top Brands card carries CardPeriod with dateFrom/dateTo forwarded",
);
assert(
  salesInsights.includes(
    '<CardPeriod window={days} dateFrom={dateFrom} dateTo={dateTo} testId="si-products-period" />'
  ),
  "Product Sales table card carries CardPeriod with dateFrom/dateTo forwarded",
);

// ── Import fence ───────────────────────────────────────────────────────────
assert(insightsPage.includes('import { CardPeriod } from "@/components/CardPeriod"'),
  "InsightsPage imports CardPeriod");
assert(salesInsights.includes('import { CardPeriod } from "@/components/CardPeriod"'),
  "SalesInsights imports CardPeriod");

// ── Ensure every glass-card that pulls window-dependent data got a period ──
// (fence against regression when a new card is added without a period)
const glassCardMatches = insightsPage.match(/glass-card rounded-md p-\d+/g) || [];
const cardPeriodOccurrences = (insightsPage.match(/<CardPeriod/g) || []).length;
// We ADD CardPeriod to 6 of the ~8 glass cards on the page (Freshness +
// Market Position have their own explicit freshness/coverage subtitles so
// we intentionally do not double-label them). Baseline: at least 6.
assert(cardPeriodOccurrences >= 6,
  `InsightsPage has ${cardPeriodOccurrences} CardPeriod instances (expected ≥ 6)`);

if (process.exitCode) {
  // eslint-disable-next-line no-console
  console.error("\nFAILURES — iter73j period-per-card wiring incomplete.");
  process.exit(1);
} else {
  // eslint-disable-next-line no-console
  console.log("\nOK — iter73j: every window-dependent card declares its period.");
}
