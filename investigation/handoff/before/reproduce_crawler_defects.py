"""Offline audit: execute exact AST-extracted functions from the supplied ZIP.

No application import, network, database or external dependencies. Synthetic
fixtures below demonstrate code behavior, not the contents of production.
"""
import ast
import asyncio
import json
import logging
import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
import sys
ROOT = Path(sys.argv[1]).resolve()
from types import SimpleNamespace

SOURCE = ROOT / 'backend' / 'crawlers.py'
GLOBALS = dict(re=re, uuid=uuid, logger=logging.getLogger('offline-audit'),
               datetime=datetime, timezone=timezone, asyncio=asyncio)


def extract(path, names):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    selected = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            selected.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in names for target in node.targets
        ):
            selected.append(node)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), 'exec'), GLOBALS)


extract(ROOT / 'backend' / 'core' / 'utils.py', {
    '_BARCODE_LEAD_RE', 'barcode_keys', 'canonical_barcode',
})
extract(SOURCE, {
    'KNOWN_BRANDS', 'SOLD_FIELD_CANDIDATES', '_SOLD_CAP_RE', '_NUMERIC_BARCODE_RE',
    'KSA_VAT_RATE', '_PRODUCT_URL_ID_RE', '_EAN_MATCH_RE',
    '_extract_sold_count', '_normalize_raw_product', '_price_amount', '_collect_variant_field_list',
    '_extract_price_from_text', '_absolutize_url', 'storefront_shelf_price',
    'resolve_own_price', 'build_key_index', '_storefront_price_index',
    'storefront_price_lookup', 'product_url_id', '_paginate_endpoint',
    '_select_salla_variant_barcode', '_finalize_crawl_log',
    'extract_brand', 'guess_category', 'guess_animal', 'extract_weight',
    'extract_store_category_names', 'process_crawled_products',
})
# Classification is outside this audit; a harmless stub isolates persistence.
GLOBALS['classify_food_subcategory_hybrid'] = lambda *a: None
GLOBALS['guess_category'] = lambda *a: 'unclassified'
GLOBALS['ledger'] = SimpleNamespace(crawl_observation=lambda n: n)


async def ignore_ledger(*args, **kwargs):
    pass


GLOBALS['ledger'].record_observations = ignore_ledger

async def fixture_polite_get(client, url, params=None):
    return await client.get(url, params)

GLOBALS['polite_get'] = fixture_polite_get


class Collection:
    def __init__(self):
        self.rows = []
        self.updates = []

    async def find_one(self, query):
        return next((r for r in self.rows if all(r.get(k) == v for k, v in query.items())), None)

    async def insert_one(self, row):
        self.rows.append(dict(row))

    async def update_one(self, query, update):
        self.updates.append({'query': query, 'update': update})
        row = await self.find_one(query)
        if row:
            row.update(update.get('$set', {}))


async def main():
    n = GLOBALS['_normalize_raw_product']
    out = {}

    row = {'id': 1, 'sku': 'ZID-1', 'name': 'Food', 'price': 100, 'effective_price': 75}
    out['competitor_effective_price_ignored'] = {
        'fixture': row, 'competitor_result': n(row, 'Demo')['price'],
        'own_store_shelf_result': GLOBALS['storefront_shelf_price'](row)[0],
    }

    row = {'id': 1, 'name': 'Food 1kg / 10kg', 'sku': 'ROOT', 'price': 200,
           'skus': [{'sku': 'SMALL', 'barcode': '1234567890123', 'price': 20,
                     'stock_quantity': 0},
                    {'sku': 'LARGE', 'barcode': '9876543210987', 'price': 200,
                     'stock_quantity': 10}], 'quantity': 10, 'is_available': True}
    first = n(row, 'Demo')
    reversed_row = dict(row, skus=list(reversed(row['skus'])))
    second = n(reversed_row, 'Demo')
    out['variant_order_changes_price_for_same_root_sku'] = {
        'first': {k: first[k] for k in ('sku', 'barcode', 'price', 'qty', 'in_stock')},
        'reversed': {k: second[k] for k in ('sku', 'barcode', 'price', 'qty', 'in_stock')},
    }

    row = {'name': 'HTML Food', 'price': 80, 'sale_price': 80,
           'original_price': 100, 'quantity': 0, 'status': 'sale'}
    a, b = n(row, 'Demo'), n(row, 'Demo')
    out['tier3_emitted_record_is_unstable_and_loses_discount'] = {
        'fixture_matches_tier3_output_shape': row,
        'first': {k: a[k] for k in ('sku', 'price', 'original_price', 'sale_price', 'in_stock')},
        'second_sku': b['sku'], 'same_sku': a['sku'] == b['sku'],
    }

    out['arabic_decimal_price_truncated'] = {
        'fixture': '١٢٣٫٤٥ ر.س', 'result': GLOBALS['_extract_price_from_text']('١٢٣٫٤٥ ر.س')}
    out['invalid_price_not_rejected'] = {
        'missing_price_becomes': n({'sku': 'MISSING', 'name': 'Food'}, 'Demo')['price'],
        'nan_string_accepted': math.isnan(n({'sku': 'NAN', 'name': 'Food', 'price': 'NaN'}, 'Demo')['price']),
        'USD_accepted_as_unlabelled_amount': n({'sku': 'USD', 'name': 'Food',
                                              'price': {'amount': 10, 'currency': 'USD'}}, 'Demo')['price'],
    }

    db = SimpleNamespace(products=Collection(), product_snapshots=Collection())
    for store, row in [
        ({'id': 'A', 'name': 'Alpha', 'domain': 'alpha.invalid'},
         {'sku': 'LOCAL-100', 'name': 'Cat food 1kg', 'price': 25, 'barcode': '1111111111111'}),
        ({'id': 'B', 'name': 'Beta', 'domain': 'beta.invalid'},
         {'sku': 'LOCAL-100', 'name': 'Dog cage', 'price': 500, 'barcode': '2222222222222'}),
    ]:
        await GLOBALS['process_crawled_products'](db, store, [row], datetime.now(timezone.utc))
    out['different_store_skus_collide'] = {
        'product_count': len(db.products.rows),
        'catalog_product': {k: db.products.rows[0][k] for k in ('sku', 'barcode', 'name_ar')},
        'snapshots': [{k: r[k] for k in ('product_id', 'store_id', 'sku', 'barcode', 'price')}
                      for r in db.product_snapshots.rows],
        'same_product_id': db.product_snapshots.rows[0]['product_id'] == db.product_snapshots.rows[1]['product_id'],
    }

    class HTTP:
        def __init__(self):
            self.requested = []
        async def get(self, url, params):
            self.requested.append(params['page'])
            page = params['page']
            # Three declared pages of 12; current paginator ignores next/pages_count.
            body = {'products': [{'id': i} for i in range((page-1)*12, page*12)],
                    'pages_count': 3, 'next': 'page3' if page < 3 else None}
            return SimpleNamespace(status_code=200, json=lambda: body)

    client = HTTP()
    rows = await GLOBALS['_paginate_endpoint'](
        client, {'url': 'https://example.invalid/products', 'pagination': 'page'},
        [{'id': i} for i in range(12)])
    out['pagination_stops_before_declared_end'] = {
        'expected_rows': 36, 'actual_rows': len(rows), 'requested_pages': client.requested}

    db = SimpleNamespace(crawl_logs=Collection(), stores=Collection())
    db.stores.rows.append({'id': 'OWN'})
    await GLOBALS['_finalize_crawl_log'](db, {
        'tier_used': 0, 'error': None, 'products_found': 2233}, 'OWN')
    out['successful_authenticated_sync_labelled_failed'] = db.stores.rows[0]

    rows = [{'sku': 'UNIT', 'barcode': '9003579308936', 'price': 20},
            {'sku': 'CASE', 'barcode': '9003579308936carton', 'price': 240}]
    idx = GLOBALS['_storefront_price_index'](rows)
    hit = GLOBALS['storefront_price_lookup'](idx, sku='UNMATCHED', barcode='9003579308936')
    out['barcode_alias_collision_overwrites_unit_with_carton'] = {
        'fixture': rows, 'unit_lookup_result': hit,
    }

    out['vat_unknown_remains_unverified_but_numeric'] = {
        'merchant_ex_vat_100_unknown_tax': GLOBALS['resolve_own_price'](None, 100),
    }
    dest = Path(__file__).with_name('crawler_repro_results.json')
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(out, indent=2, ensure_ascii=True))


if __name__ == '__main__':
    asyncio.run(main())
