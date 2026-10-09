"""Explicit seller scope; independent of the 'store carries product' row filter."""
from fastapi import HTTPException
from observation_contract import stable_id


async def resolve(db, mode="all", competitor_ids=None):
    if mode not in {"all", "selected"}:
        raise HTTPException(422, "comparison_mode must be all or selected")
    stores = await db.stores.find({"is_active": {"$ne": False}}, {"_id": 0, "id": 1, "name": 1, "is_own_store": 1}).to_list(10000)
    candidates = {s["id"]: s for s in stores if not s.get("is_own_store")}
    requested = sorted(set(v.strip() for v in str(competitor_ids or "").split(",") if v.strip()))
    if any(v not in candidates for v in requested):
        raise HTTPException(422, "Selected competitor is inactive, unknown, or your own store")
    ids = sorted(candidates) if mode == "all" else requested
    return {"mode": mode, "competitor_ids": ids, "competitor_names": [candidates[v]["name"] for v in ids],
            "scope_id": stable_id("comparison-scope-v1", mode, ids),
            "membership_filter_is_separate": True}


class ScopedCSVWriter:
    def __init__(self, writer, scope, membership):
        self.writer, self.scope, self.membership, self.first = writer, scope, membership, True

    def writerow(self, row):
        extra = (["Comparison mode", "Compared competitor IDs", "Comparison scope ID", "Store-membership filter"] if self.first
                 else [self.scope["mode"], ",".join(self.scope["competitor_ids"]), self.scope["scope_id"], self.membership or ""])
        self.first = False
        return self.writer.writerow([*row, *extra])