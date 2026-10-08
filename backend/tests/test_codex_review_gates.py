"""Independent release gates. Local disposable Mongo only; no store requests."""
import asyncio
import os
import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

setup = SimpleNamespace(ROOT=Path(__file__).resolve().parents[2])
import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError
import observation_contract as oc
import catalog_pagination
import crawlers
import ingest_v2
import integrity_indexes
import evidence_ledger
import market_share
import price_cohort
import comparison_views
import store_views
import job_control
import server

LOOP = asyncio.new_event_loop()
def run(coro):
    return LOOP.run_until_complete(coro)

@pytest.fixture
def db():
    name = 'codex_independent_' + uuid.uuid4().hex
    url = os.environ.get('DALEEL_TEST_MONGO_URL', 'mongodb://127.0.0.1:27087')
    from urllib.parse import urlparse
    if urlparse(url).hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise RuntimeError('Independent gates require a disposable loopback MongoDB')
    client = AsyncIOMotorClient(url, io_loop=LOOP)
    database = client[name]
    yield database
    assert name.startswith('codex_independent_')
    run(client.drop_database(name))
    client.close()

def store(sid='comp', own=False):
    return {'id':sid, 'name':sid, 'domain':sid+'.example.org', 'platform':'zid', 'is_active':True, 'is_own_store':own}

def raw(**kw):
    return {'id':'p1','sku':'LOCAL','name':'Food 1kg','price':20,'quantity':5, **kw}

def snap(oid='a', **kw):
    return {'offer_id':oid,'sku':oid,'store_id':'comp','store_name':'comp','price':20,
            'observation_version':2,'is_synthetic':False,'comparable':True,'currency':'SAR',
            'price_basis':'storefront_inc_vat','in_stock':True,'confidence_score':99,
            'crawled_at':datetime.now(timezone.utc), **kw}

def test_startup_preserves_store_scoped_duplicate_skus(db):
    async def go():
        await integrity_indexes.ensure(db)
        await server.ensure_all_indexes(db)
        s1,s2=store('s1'),store('s2')
        now=datetime.now(timezone.utc)
        await crawlers.process_crawled_products(db,s1,[raw()],now)
        await crawlers.process_crawled_products(db,s2,[raw()],now)
        assert await db.products.count_documents({'sku':'LOCAL'}) == 2
    run(go())

def test_external_variants_survive_ingestion(db):
    async def go():
        s=store(); await db.stores.insert_one(s)
        payload=SimpleNamespace(domain=s['domain'],store_id=s['id'],run_id='variants',
            observed_at=datetime.now(timezone.utc).isoformat(),catalog_complete=True,
            products=[{'listing_id':'p1','variant_id':v,'sku':'LOCAL','price':p,'currency':'SAR',
                       'price_basis':'storefront_inc_vat','quantity':4} for v,p in [('small',20),('large',200)]])
        await ingest_v2.ingest(db,payload)
        rows=await db.product_snapshots.find({}, {'_id':0,'variant_id':1,'price':1}).to_list(10)
        assert {r['variant_id'] for r in rows} == {'small','large'}, rows
    run(go())

def test_empty_page_with_more_pages_is_incomplete():
    async def go():
        ep={'url':'https://fixture.example.org/api','pagination':'page',
            '_initial_body':{'data':[{'id':1}],'total_pages':3,'next':True}}
        async def fetch(*a,**k):
            return SimpleNamespace(status_code=200,json=lambda:{'data':[],'total_pages':3,'next':True})
        await catalog_pagination.paginate(None,ep,[{'id':1}],fetch)
        assert ep['_pagination']['complete'] is False, ep['_pagination']
    run(go())

def test_tier1_supplement_reaches_snapshot_identity(db):
    async def go():
        rows=[raw()]
        ep={'tag':'fixture','url':'https://fixture.example.org/api','_pagination':{'complete':True}}
        async def supplement(_db,_store,items,_log): items[0]['barcode']='4006381333931'
        with patch.object(crawlers,'resolve_proxy_for',new=AsyncMock(return_value=None)), \
             patch.object(crawlers,'_try_single_endpoint',new=AsyncMock(return_value=(rows,ep))), \
             patch.object(crawlers,'_paginate_endpoint',new=AsyncMock(return_value=rows)), \
             patch.object(crawlers,'_detect_soft_block',new=AsyncMock(return_value=(False,None))), \
             patch.object(crawlers,'_maybe_salla_detail_supplement',new=supplement):
            await crawlers.crawl_salla_tier1(db,store())
        row=await db.product_snapshots.find_one({})
        assert row['barcode']=='4006381333931', row['barcode']
    run(go())

def test_replay_repairs_interrupted_evidence_write(db):
    async def go():
        now=datetime.now(timezone.utc)
        with patch.object(evidence_ledger,'record',new=AsyncMock(side_effect=RuntimeError('simulated write interruption'))):
            with pytest.raises(RuntimeError):
                await crawlers.process_crawled_products(db,store(),[raw()],now)
        await crawlers.process_crawled_products(db,store(),[raw()],now)
        assert await db.observation_events.count_documents({})==1
    run(go())

def test_conflicting_explicit_barcodes_override_numeric_local_sku():
    own={'barcode':'01234567890128','sku':'4006381333931','name_en':'Food 1kg'}
    other={'barcode':'4006381333931','sku':'4006381333931','name_en':'Food 1kg'}
    assert price_cohort.identity_agrees(own,other) is False
    assert price_cohort.identity_agrees(own,other,manual=True) is False

def test_group_shares_do_not_mix_denominators_or_invent_zero():
    rows=[{'sku':'A','name':'A','brand':'Brand','my_units':50,'my_revenue':500,
           'market_units':None,'market_revenue':None,'share_comparable':False},
          {'sku':'B','name':'B','brand':'Brand','my_units':None,'my_revenue':None,
           'market_units':10,'market_revenue':100,'share_comparable':False}]
    group=market_share.aggregate_groups(rows,[],'brand')[0]
    assert group['my_unit_share_pct'] is None, group['my_unit_share_pct']
    unknown=market_share.aggregate_groups([rows[0]|{'my_units':None,'my_revenue':None}],[],'brand')[0]
    assert unknown['units'] is None and unknown['revenue'] is None

def test_missing_current_trend_does_not_crash():
    assert market_share._delta_pct(None,10) is None

def test_stale_own_price_is_withheld():
    own={'price':100,'price_basis':'storefront_inc_vat','last_synced_at':(datetime.now(timezone.utc)-timedelta(days=90)).isoformat()}
    assert not server._effective_own_price(own)

def test_own_sync_rejects_foreign_currency(db):
    async def go():
        s=store('own',True); await db.stores.insert_one(s)
        rows=[raw(price={'amount':20,'currency':'USD'})]
        async def paginate(http,ep,items):
            ep['_pagination']={'complete':True}; return rows
        ep={'tag':'fixture','url':'https://fixture.example.org/api'}
        with patch.object(crawlers,'_fetch_zid_api_catalog',new=AsyncMock(return_value=([],'missing_token'))), \
             patch.object(crawlers,'_try_single_endpoint',new=AsyncMock(return_value=(rows,ep))), \
             patch.object(crawlers,'_paginate_endpoint',new=paginate):
            await crawlers.sync_own_store_prices(db,s)
        row=await db.my_products.find_one({})
        assert row is None or not server._effective_own_price(row), row and row.get('price')
    run(go())

def test_own_variants_do_not_overwrite_sibling(db):
    async def go():
        s=store('own',True); await db.stores.insert_one(s)
        rows=[raw(skus=[{'id':'v1','sku':'SHARED','barcode':'4006381333931','price':20,'quantity':1},
                        {'id':'v2','sku':'SHARED','barcode':'01234567890128','price':200,'quantity':2}])]
        async def paginate(http,ep,items): ep['_pagination']={'complete':True}; return rows
        ep={'tag':'fixture','url':'https://fixture.example.org/api'}
        with patch.object(crawlers,'_fetch_zid_api_catalog',new=AsyncMock(return_value=([],'missing_token'))), \
             patch.object(crawlers,'_try_single_endpoint',new=AsyncMock(return_value=(rows,ep))), \
             patch.object(crawlers,'_paginate_endpoint',new=paginate):
            await crawlers.sync_own_store_prices(db,s)
        rows=await db.my_products.find({}, {'_id':0,'barcode':1,'price':1}).to_list(10)
        assert not any(r.get('barcode')=='4006381333931' and r['price']==200 for r in rows),rows
    run(go())

def test_store_profile_redacts_credentials(db):
    async def go():
        s=store(); s['tier4_password']='AUDIT_SENTINEL_ENCRYPTED'; await db.stores.insert_one(s)
        result=await store_views.profile(db,s['id'],AsyncMock(return_value=None))
        assert 'tier4_password' not in result['store']
    run(go())

def test_compose_supplies_required_encryption_config():
    import yaml
    compose=yaml.safe_load((setup.ROOT/'deploy/docker-compose.yml').read_text())
    assert 'ENCRYPTION_KEY' in compose['services']['backend']['environment']

def test_stock_rate_includes_out_of_stock_offers(db):
    async def go():
        await db.stores.insert_one(store())
        await db.product_snapshots.insert_many([snap('available'),snap('unavailable',in_stock=False)])
        result=await store_views.ranking(db,AsyncMock(return_value=None))
        assert result['stores'][0]['in_stock_pct']==50,result['stores'][0]['in_stock_pct']
    run(go())

def test_out_of_range_money_is_quarantined_without_exception():
    assert oc.money('1e100') is None

def test_failed_crawl_job_does_not_report_completed(db):
    async def go():
        await db.stores.insert_one(store())
        with patch.object(server,'db',db),patch.object(server,'crawl_paused',False), \
             patch.object(server,'crawl_store_waterfall',new=AsyncMock(return_value={'status':'failed','error':'source_timeout'})), \
             patch.object(server,'_recompute_store_metrics',new=AsyncMock()), \
             patch.object(server,'maybe_recompute_dashboard_cache',new=AsyncMock()), \
             patch.object(server,'maybe_recompute_page_caches',new=AsyncMock()):
            rid,_=await job_control.queue(db,'crawl','failed-fixture')
            await job_control.execute(db,rid,'crawl',lambda:server.scheduled_crawl_job('comp'))
        row=await db.job_runs.find_one({'id':rid})
        assert row['status']!='completed',row['status']
    run(go())

def test_reviewed_offer_brand_affects_comparison(db):
    async def go():
        await db.stores.insert_many([store('own',True),store('comp')])
        own={'sku':'own-sku','barcode':'4006381333931','price':20,'brand':'Royal Canin','brand_source':'reviewed'}
        await db.products.insert_one({'offer_id':'offer','store_id':'comp','sku':'other','brand':'Royal Canin','brand_source':'reviewed'})
        await db.product_snapshots.insert_one(snap('offer',sku='other',barcode='4006381333931',brand='Whiskas',brand_source='store_supplied'))
        result=await price_cohort.build_cohorts(db,[own],'own',lambda r:20)
        assert len(result['own-sku']['sellers'])==1
        import verified_matching
        observed=await db.product_snapshots.find_one({}, {'_id':0})
        matches=await verified_matching.match(db,own,snapshots=[observed],own_store_id='own')
        assert len(matches)==1
    run(go())

def test_market_share_price_rank_uses_same_eligible_offers(db):
    async def go():
        now=datetime.now(timezone.utc)
        await db.stores.insert_many([store('own',True),store('comp'),store('oos')])
        await db.my_products.insert_one({'sku':'own','barcode':'4006381333931','price':100,
            'price_basis':'storefront_inc_vat','last_synced_at':now.isoformat(),'in_stock':True})
        await db.product_snapshots.insert_many([
            snap('live',barcode='4006381333931',price=150),
            snap('oos',store_id='oos',store_name='oos',barcode='4006381333931',price=50,in_stock=False)])
        data=await market_share.build_dataset(db,30,'own',own_price_fn=server._effective_own_price,
            brand_fn=lambda *a,**k:'',category_fn=lambda *a,**k:'',orders_by_sku=None,
            min_confidence=85,window_start=now-timedelta(days=30),window_end=now,sealed=False,now=now)
        row=data['my_products'][0]
        assert row['my_price']==100
        assert row['price_rank']==1 and row['price_rank_of']==2, (row['price_rank'],row['price_rank_of'])
    run(go())

def test_methodology_does_not_call_inventory_changes_sales_floor():
    source=(setup.ROOT/'frontend/src/components/marketShare/Methodology.jsx').read_text(encoding='utf-8')
    assert 'floor rather than a total' not in source
    source=(setup.ROOT/'backend/server.py').read_text(encoding='utf-8')
    assert 'A floor, not a total:' not in source
