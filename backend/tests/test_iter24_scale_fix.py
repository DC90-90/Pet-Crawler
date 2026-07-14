"""iter24 regression tests — chunked /api/my-products + change-only own-store writes.

1. Property test backing the change-only write claim: removing snapshots whose
   (price, qty_available, sold_count) equal their predecessor's CANNOT change
   _estimate_sales_from_snapshots output (positive-delta sums and sold-counter
   diffs are invariant under equal-adjacent removal). This is the safety
   condition for writing fewer own-store snapshots.
2. The dedup guard never suppresses the daily heartbeat (first write of a day
   has no same-day predecessor by construction — verified in the sync test).
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.utils import _estimate_sales_from_snapshots  # noqa: E402


def _dedupe_equal_adjacent(snaps):
    out = []
    for s in snaps:
        if out and (
            round(float(out[-1]["price"] or 0), 2) == round(float(s["price"] or 0), 2)
            and int(out[-1]["qty_available"] or 0) == int(s["qty_available"] or 0)
            and int(out[-1]["sold_count"] or 0) == int(s["sold_count"] or 0)
        ):
            continue
        out.append(s)
    return out


def _random_series(rng, n):
    price = round(rng.uniform(5, 300), 2)
    qty = rng.choice([0, rng.randint(1, 60), 100, 250])  # incl. placeholder + >200
    sold = rng.choice([0, rng.randint(0, 400)])
    snaps = []
    for _ in range(n):
        r = rng.random()
        if r < 0.55:
            pass  # unchanged — the duplicate case change-only writes remove
        elif r < 0.75:
            d = rng.randint(1, 8)
            sold += d if sold else 0
            qty = max(0, qty - d)
        elif r < 0.85:
            qty += rng.randint(5, 80)  # restock
        elif r < 0.93:
            price = round(price * rng.uniform(0.9, 1.1), 2)
        else:
            sold = 0 if rng.random() < 0.3 else sold + rng.randint(0, 60)  # reset / spike
        snaps.append({"price": price, "qty_available": qty, "sold_count": sold})
    return snaps


def test_units_invariant_under_equal_adjacent_removal():
    """Units must be EXACTLY invariant for both estimator methods across 500
    random series — this is what makes change-only writes safe."""
    rng = random.Random(1337)
    for days in (7, 14, 30, 90):
        for _ in range(125):
            snaps = _random_series(rng, rng.randint(2, 200))
            deduped = _dedupe_equal_adjacent(snaps)
            u1, _, m1 = _estimate_sales_from_snapshots(snaps, days)
            u2, _, m2 = _estimate_sales_from_snapshots(deduped, days)
            assert u1 == u2, f"units drifted {u1}->{u2} (methods {m1}->{m2})"


def test_revenue_uses_avg_price_note():
    """Documented nuance: revenue_est = units x MEAN(price over snapshots), so
    when the price CHANGES inside a window, removing duplicate rows reweights
    the mean slightly. With a constant price (the overwhelmingly common case
    intra-day) revenue is exactly invariant — pinned here."""
    snaps = [{"price": 50.0, "qty_available": 30 - i, "sold_count": 0} for i in range(10)]
    dup = []
    for s in snaps:
        dup.append(s)
        dup.append(dict(s))  # duplicate every row
    u1, r1, _ = _estimate_sales_from_snapshots(snaps, 30)
    u2, r2, _ = _estimate_sales_from_snapshots(_dedupe_equal_adjacent(dup), 30)
    assert (u1, r1) == (u2, r2)
