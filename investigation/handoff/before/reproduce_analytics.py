"""Offline reproductions against the provided ZIP source, using only stdlib.

AST-extracts actual repository functions without importing server/startup or
connecting to any database. A small in-memory DB adapter records function writes.
Run with Python 3; optional first argument is source root. No network operations.
"""
import ast
import asyncio
import copy
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import sys
ROOT = Path(sys.argv[1]).resolve()
import random
import statistics
import sys
from types import SimpleNamespace
import uuid

BACKEND = ROOT / 'backend'

def extract(filename, names, namespace):
    tree = ast.parse((BACKEND / filename).read_text(encoding='utf-8'))
    selected = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            node.decorator_list = []
            selected.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in node.targets):
            selected.append(node)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(BACKEND / filename), 'exec'), namespace)
    return namespace

def matches(row, query):
    for key, value in query.items():
        observed = row.get(key)
        if isinstance(value, dict):
            for op, bound in value.items():
                if op == '$gte' and not (observed is not None and observed >= bound): return False
                if op == '$lt' and not (observed is not None and observed < bound): return False
        elif observed != value:
            return False
    return True

class Cursor:
    def __init__(self, rows): self.rows = rows
    def batch_size(self, _): return self
    def __aiter__(self):
        self.iterator = iter(self.rows)
        return self
    async def __anext__(self):
        try: return next(self.iterator)
        except StopIteration: raise StopAsyncIteration
    async def to_list(self, n=None, length=None): return self.rows[:n or length]

class Collection:
    def __init__(self, rows=None): self.rows = copy.deepcopy(rows or [])
    def find(self, q=None, projection=None): return Cursor([copy.deepcopy(r) for r in self.rows if matches(r, q or {})])
    async def find_one(self, q, projection=None): return next((copy.deepcopy(r) for r in self.rows if matches(r, q)), None)
    async def count_documents(self, q): return sum(matches(r, q) for r in self.rows)
    async def insert_one(self, row): self.rows.append(copy.deepcopy(row))
    async def insert_many(self, rows): self.rows.extend(copy.deepcopy(rows))
    async def create_index(self, *args, **kwargs): pass
    async def delete_many(self, q): self.rows = [r for r in self.rows if not matches(r, q)]
    async def update_one(self, q, update, upsert=False):
        row = next((r for r in self.rows if matches(r, q)), None)
        if row is None:
            if not upsert: return
            row = {k:v for k,v in q.items() if not isinstance(v, dict)}
            row.update(copy.deepcopy(update.get('$setOnInsert', {})))
            self.rows.append(row)
        row.update(copy.deepcopy(update.get('$set', {})))
        for key, delta in update.get('$inc', {}).items(): row[key] = row.get(key, 0) + delta

class DB:
    def __init__(self): self.collections = {}
    def __getattr__(self, name): return self.collections.setdefault(name, Collection())

NS = {'datetime':datetime, 'timedelta':timedelta, 'timezone':timezone, 'statistics':statistics,
      'logger':logging.getLogger('audit'), 'random':random, 'uuid':uuid, 'os':os,
      'jsonable_encoder':lambda x:x}
extract('core/utils.py', {'PLACEHOLDER_QTY_VALUES', 'MAX_QTY_DELTA_PER_INTERVAL', 'MAX_DAILY_SALES_PER_SKU',
        'MAX_SOLD_COUNT_DELTA_PER_INTERVAL','MIN_AGGREGATION_CONFIDENCE','_estimate_sales_from_snapshots'}, NS)
extract('server.py', {'seed_database','STORES_SEED','PRODUCTS_SEED','EXTRA_PRODUCT_TEMPLATES',
        '_metric_day_str','_recompute_store_metrics','_own_orders_aggregate','_ranking_revenue_value',
        'DASHBOARD_CACHE_MAX_AGE_SECS','_page_cache_key','_serve_page_cache'}, NS)
extract('zid_orders.py', {'aggregate_orders'}, NS)
extract('ledger.py', {'LEDGER_WRITER_VERSION','KSA_TZ','ksa_day_str','_store_day_id','_row_id',
        'record_observations'}, NS)
NS['DuplicateKeyError'] = type('DuplicateKeyError', (Exception,), {})
NS['OperationFailure'] = type('OperationFailure', (Exception,), {})

def snap(qty, sold=0, price=10, at=None):
    return {'sku':'SKU', 'store_id':'store', 'qty_available':qty, 'sold_count':sold, 'price':price,
            'confidence_score':99, 'source_tier':1, 'in_stock':True,
            'crawled_at':at or datetime(2026,10,1,6,tzinfo=timezone.utc)}

async def main():
    output = {'scope':'Offline provided-source reproductions, not a production database audit', 'cases':{}}
    cases = output['cases']
    estimate = NS['_estimate_sales_from_snapshots']
    cases['missing_quantity_becomes_sales'] = {'input':[20,None], 'result':estimate([snap(20),snap(None)],30)}
    cases['missing_counter_becomes_sales'] = {'input':[100,None,100], 'result':estimate([snap(10,100),snap(10,None),snap(10,100)],30)}
    cases['advertised_10_unit_cap_not_applied'] = {'input':[40,0], 'result':estimate([snap(40),snap(0)],30)}
    cases['constant_counter_falls_back_to_stock_depletion'] = {'counter':[100,100], 'qty':[20,10],
       'result':estimate([snap(20,100),snap(10,100)],30)}
    cases['stock_revenue_labeled_exact'] = {'input':{'revenue_30d':200, 'revenue_status':'computed'},
        'result':NS['_ranking_revenue_value']({'revenue_30d':200,'revenue_status':'computed'})}

    # Execute the real per-row share calculation block with valid derived inputs.
    tree = ast.parse((BACKEND/'server.py').read_text(encoding='utf-8'))
    function = next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_my_products_dataset')
    share_block = next(n for n in function.body if isinstance(n, ast.For) and isinstance(n.target,ast.Name) and n.target.id=='r')
    share_env = {'result':[{'qty_sold_est':10, 'my_units_sold':20, 'num_priced_competitors':1}]}
    exec(compile(ast.Module(body=[share_block],type_ignores=[]),str(BACKEND/'server.py'),'exec'),share_env)
    cases['exact_order_numerator_snapshot_denominator'] = share_env['result'][0]

    db=DB()
    NS['db']=db
    prior=os.environ.pop('SEED_DEMO_DATA',None)
    try: await NS['seed_database']()
    finally:
        if prior is not None: os.environ['SEED_DEMO_DATA']=prior
    seeded=db.product_snapshots.rows
    cases['default_empty_database_seed'] = {'stores':len(db.stores.rows),'products':len(db.products.rows),
       'invented_snapshots':len(seeded), 'earliest':min(s['crawled_at'] for s in seeded),
       'count_with_confidence_at_least_85':sum(s['confidence_score']>=85 for s in seeded),
       'has_explicit_synthetic_flag':any('synthetic' in s or 'is_demo' in s or 'data_source' in s for s in seeded)}

    db=DB()
    at=datetime(2026,10,1,6,tzinfo=timezone.utc)
    readings=[snap(10,at=at),snap(5,at=at+timedelta(hours=1)),snap(10,at=at+timedelta(hours=2))]
    db.product_snapshots.rows=readings
    await NS['_recompute_store_metrics'](db,'store')
    cases['intraday_sales_dropped_by_rollup']={'snapshot_estimator':estimate(readings,1),
       'daily_sales_documents':db.sku_sales_daily.rows}

    db=DB()
    at=datetime(2026,10,1,11,tzinfo=timezone.utc)
    writer=NS['record_observations']
    await writer(db,'store','Store',[{'sku':'SKU','close_price':200}],at,crawl_run_id='run-later')
    await writer(db,'store','Store',[{'sku':'SKU','close_price':100}],at-timedelta(hours=4),crawl_run_id='run-earlier')
    await writer(db,'store','Store',[{'sku':'SKU','close_price':100}],at-timedelta(hours=4),crawl_run_id='run-earlier')
    cases['ledger_old_event_overwrites_new_and_replay_increments']=db.daily_ledger.rows[0]

    db=DB()
    cases['complete_zero_order_window_returns_missing']=await NS['_own_orders_aggregate'](db,at)
    db.own_store_orders.rows=[{'created_at':at,'excluded':True,'total':100,'units':2,'items':[]}]
    cases['cancelled_only_window_returns_missing']=await NS['_own_orders_aggregate'](db,at)

    db=DB()
    db.dashboard_cache.rows=[{'key':'example:v1:days=30','computed_at':datetime.now(timezone.utc)-timedelta(hours=23),
       'payload':{'cached_value':'23-hour-old figure'}}]
    async def should_not_run(): raise AssertionError('Live recomputation unexpectedly ran')
    body,meta=await NS['_serve_page_cache'](db,'example',30,should_not_run)
    cases['23_hour_cache_marked_fresh']={'body':body,'meta':meta}

    target=Path(__file__).with_name('reproduction-results.json')
    target.write_text(json.dumps(output,indent=2,default=str),encoding='utf-8')
    print(json.dumps(output,indent=2,default=str))

if __name__=='__main__': asyncio.run(main())
