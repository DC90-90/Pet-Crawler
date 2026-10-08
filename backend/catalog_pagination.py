"""Pagination with evidence of completion, never a short-page heuristic."""
from urllib.parse import urljoin, urlparse
from observation_contract import stable_id


async def paginate(http, ep, initial, fetch, max_pages=200):
    from crawlers import _sf_items, _sf_page_meta
    rows, seen, cursors = [], set(), set()
    meta = {"complete": False, "pages_fetched": 1, "stop_reason": "unknown", "expected_count": None}
    body = ep.get("_initial_body") or {}

    def add(items):
        fresh = []
        for row in items:
            if not isinstance(row, dict):
                continue
            key = str(row.get("id") or row.get("sku") or stable_id(row))
            if key not in seen:
                seen.add(key)
                fresh.append(row)
        rows.extend(fresh)
        return len(fresh)

    add(initial)
    for page in range(1, max_pages + 1):
        total_pages, total, has_next = _sf_page_meta(body)
        meta["expected_count"] = total if total is not None else meta["expected_count"]
        legacy = ep.get("_legacy_pagination") or {}
        if total_pages is None and page == 1:
            total_pages = legacy.get("last_page")
        cursor_mode = ep.get("pagination") == "cursor"
        cursor = body.get("cursor")
        next_url = cursor.get("next") if isinstance(cursor, dict) else (ep.get("_cursor_next") if page == 1 else None)
        terminal = (has_next is False or (total_pages is not None and page >= total_pages)
                    or (cursor_mode and isinstance(cursor, dict) and not next_url))
        if terminal:
            meta.update(complete=meta["expected_count"] is None or len(rows) >= meta["expected_count"], stop_reason="explicit_end")
            if not meta["complete"]:
                meta["stop_reason"] = "count_mismatch"
            break
        if page == max_pages:
            meta["stop_reason"] = "page_cap"
            break
        url, params = ep["url"], {**ep.get("params", {}), "page": page + 1}
        if cursor_mode:
            if not next_url:
                meta["stop_reason"] = "missing_pagination_metadata"
                break
            url, params = urljoin(ep["url"], next_url), None
            if urlparse(url).netloc != urlparse(ep["url"]).netloc or url in cursors:
                meta["stop_reason"] = "invalid_or_duplicate_cursor"
                break
            cursors.add(url)
            if ep.get("tag", "").startswith("/en/") and "/en/api/" not in url:
                url = url.replace("/api/", "/en/api/", 1)
        try:
            response = await fetch(http, url, params=params)
            if response is None or response.status_code != 200:
                meta["stop_reason"] = f"http_{response.status_code if response is not None else 'timeout'}"
                break
            body = response.json()
            if not isinstance(body, (dict, list)) or (isinstance(body, dict) and
                    (body.get("success") is False or str(body.get("status", "")).lower() in ("error", "failed", "blocked"))):
                meta["stop_reason"] = "upstream_error_payload"
                break
            items = _sf_items(body)
            meta["pages_fetched"] += 1
            if not items:
                nested = body.get("data") if isinstance(body, dict) else None
                lists_present = isinstance(body, list) or (isinstance(body, dict) and any(isinstance(body.get(k), list) for k in ("data", "products", "results"))) or (isinstance(nested, dict) and any(isinstance(nested.get(k), list) for k in ("products", "results", "data")))
                if not lists_present:
                    meta["stop_reason"] = "malformed_empty_page"
                    break
                empty_pages, empty_total, empty_next = _sf_page_meta(body)
                expected = empty_total if empty_total is not None else meta["expected_count"]
                meta['expected_count'] = expected
                cursor = body.get('cursor') if isinstance(body, dict) else None
                more = (empty_next is True or (empty_pages is not None and page + 1 < empty_pages)
                        or (isinstance(cursor, dict) and bool(cursor.get('next')))
                        or (total_pages is not None and page + 1 < total_pages))
                meta.update(complete=not more and (expected is None or len(rows) >= expected),
                            stop_reason='contradictory_empty_page' if more else 'empty_page')
                break
            if not add(items):
                meta["stop_reason"] = "duplicate_page"
                break
        except Exception as exc:
            meta["stop_reason"] = type(exc).__name__
            break
    meta["products_observed"] = len(rows)
    ep["_pagination"] = meta
    return rows
