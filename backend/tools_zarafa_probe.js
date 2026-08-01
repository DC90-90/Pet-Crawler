// Read-only ground-truth probe for the two Zarafa cases.
// Run:  mongosh "<atlas-uri>/<db>" tools_zarafa_probe.js
// Writes nothing. Reads stores, product_snapshots, product_matches.

const CASES = [
  { label: "A  Hills GI Biome",    sku: "052742059518", extra: ["52742059518", "607650"] },
  { label: "B  RC Sensible 33",    sku: "3182550702263", extra: ["03182550702263"] },
];

const zarafa = db.stores.findOne({ domain: /zarafa/i }, { id: 1, name: 1, domain: 1, platform: 1 });
print("Zarafa store: " + JSON.stringify(zarafa));
if (!zarafa) { quit(1); }
const ZID = zarafa.id;
const NOW = new Date();
const D30 = new Date(NOW.getTime() - 30 * 864e5);

for (const c of CASES) {
  print("\n================ " + c.label + "  (our sku " + c.sku + ") ================");

  // ── FACT 1 — does a Zarafa snapshot exist for this product? ──────────────
  // Two ways it could be stored: under our identifier, or under Zarafa's own
  // SKU reached through product_matches. Both are checked.
  const matches = db.product_matches.find({
    $or: [{ my_sku: c.sku }, { competitor_sku: c.sku }],
    competitor_store_id: ZID,
  }).toArray();
  const matchedSkus = matches.map(m => m.competitor_sku);
  const skuSet = [c.sku].concat(c.extra).concat(matchedSkus);

  const snaps = db.product_snapshots.find(
    { store_id: ZID, sku: { $in: skuSet } },
    { sku: 1, price: 1, crawled_at: 1, in_stock: 1, confidence_score: 1, product_url: 1 }
  ).sort({ crawled_at: -1 }).limit(5).toArray();

  print("1. Zarafa snapshot exists?  " + (snaps.length ? "YES" : "NO"));
  snaps.forEach(s => print("     sku=" + s.sku + "  price=" + s.price +
    "  crawled_at=" + s.crawled_at + "  conf=" + s.confidence_score +
    "  url=" + (s.product_url || "-")));
  if (!snaps.length) {
    // widen: is Zarafa being crawled at all, and does it carry the name?
    const tot = db.product_snapshots.countDocuments({ store_id: ZID });
    const last = db.product_snapshots.find({ store_id: ZID }, { crawled_at: 1 })
      .sort({ crawled_at: -1 }).limit(1).toArray();
    print("     (Zarafa snapshots total=" + tot + ", latest=" +
      (last[0] ? last[0].crawled_at : "none") + ")");
  }

  // ── FACT 2 — does a match link Zarafa to our product? ────────────────────
  print("2. product_matches row?     " + (matches.length ? "YES" : "NO"));
  matches.forEach(m => print("     my_sku=" + m.my_sku + "  competitor_sku=" + m.competitor_sku +
    "  confidence=" + m.confidence + "  method=" + (m.match_method || m.method || "-")));

  // ── FACT 3 — does the CURRENT endpoint's seller list include Zarafa? ─────
  // This reproduces the live filter verbatim:
  //   product_snapshots WHERE sku == <our sku> AND crawled_at >= now-30d
  const shown = db.product_snapshots.distinct("store_id",
    { sku: c.sku, crawled_at: { $gte: D30 } });
  print("3. seller list shows Zarafa? " + (shown.indexOf(ZID) >= 0 ? "YES" : "NO"));
  print("     stores currently listed (" + shown.length + "): " +
    db.stores.find({ id: { $in: shown } }, { name: 1 }).toArray().map(s => s.name).join(", "));
}
