"""Filter and sort a list of rows by any column (27 Oct 2026 — the client
wants a filter on every column of the Market tables).

colf is JSON from the page: {"<field>": {"q": "text"} | {"min": n, "max": n} |
{"in": ["a", "b"]}}. A field is a dotted path ("top_competitor.store_name",
"trend.revenue_pct"); on a list it matches when any element matches
("competitors", "sellers.store_name"). Rows without the value never pass a
filter on it, and sort last.
"""
import json


def value(row, path):
    cur = [row]
    for part in str(path).split("."):
        nxt = []
        for c in cur:
            v = c.get(part) if isinstance(c, dict) else None
            if isinstance(v, list):
                nxt.extend(v)
            elif v is not None:
                nxt.append(v)
        cur = nxt
    return cur


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _passes(vals, rule):
    if not isinstance(rule, dict):
        return True
    q = str(rule.get("q") or "").strip().casefold()
    if q and not any(q in str(v).casefold() for v in vals):
        return False
    if rule.get("in"):
        wanted = {str(x).casefold() for x in rule["in"]}
        if not any(str(v).casefold() in wanted for v in vals):
            return False
    lo, hi = _num(rule.get("min")), _num(rule.get("max"))
    if lo is not None or hi is not None:
        nums = [n for n in (_num(v) for v in vals) if n is not None]
        if not any((lo is None or n >= lo) and (hi is None or n <= hi) for n in nums):
            return False
    return True


def parse(colf):
    if not colf:
        return {}
    try:
        spec = json.loads(colf) if isinstance(colf, str) else colf
    except ValueError:
        return {}
    return {k: v for k, v in spec.items() if isinstance(k, str) and isinstance(v, dict)} if isinstance(spec, dict) else {}


def apply(rows, colf=None, sort_by=None, sort_dir="desc"):
    spec = parse(colf)
    if spec:
        rows = [r for r in rows if all(_passes(value(r, f), rule) for f, rule in spec.items())]
    if sort_by:
        filled = [r for r in rows if value(r, sort_by)]
        blank = [r for r in rows if not value(r, sort_by)]
        firsts = [value(r, sort_by)[0] for r in filled]
        numeric = all(_num(v) is not None for v in firsts)
        order = sorted(range(len(filled)), key=lambda i: _num(firsts[i]) if numeric else str(firsts[i]).casefold(),
                       reverse=sort_dir == "desc")
        rows = [filled[i] for i in order] + blank
    return rows
