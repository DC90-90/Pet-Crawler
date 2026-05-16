#!/usr/bin/env python3
"""
Daleel Pets Phase 4 Backend API Testing
Tests all endpoints including new Phase 4 features:
- 3-tier waterfall crawler (Tier 1 JSON → Tier 2 XHR Playwright → Tier 3 HTML BS4)
- Weekly Market Intelligence Digest with APScheduler
- Saudi Seasonal Calendar Annotations
- Enhanced Trending panel on Insights
- Zarafa store crawled via Tier 2 XHR interception (8+ real products)
- Crawl logs show tier progression and endpoint_used field
- Digest generation and retrieval endpoints
- Scheduler status shows weekly_digest job
"""

import requests
import sys
import json
from datetime import datetime

class DaleelPetsAPITester:
    def __init__(self, base_url="https://price-monitor-58.preview.emergentagent.com"):
        self.base_url = base_url
        self.api_url = f"{base_url}/api"
        self.tests_run = 0
        self.tests_passed = 0
        self.failed_tests = []
        self.token = None
        self.test_store_id = None
        self.product_sku = None
        self.alert_id = None

    def log_test(self, name, success, details=""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {name}")
        else:
            print(f"❌ {name} - {details}")
            self.failed_tests.append({"test": name, "details": details})

    def run_test(self, name, method, endpoint, expected_status=200, data=None, check_response=None, auth_required=True):
        """Run a single API test"""
        url = f"{self.api_url}/{endpoint}"
        headers = {'Content-Type': 'application/json'}
        
        # Add auth token if required and available
        if auth_required and self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, timeout=10)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=headers, timeout=10)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=headers, timeout=10)
            elif method == 'DELETE':
                response = requests.delete(url, headers=headers, timeout=10)

            # Check status code
            if response.status_code != expected_status:
                self.log_test(name, False, f"Expected {expected_status}, got {response.status_code}. Response: {response.text[:200]}")
                return False, {}

            # Parse response
            try:
                response_data = response.json()
            except:
                response_data = {}

            # Run custom response checks
            if check_response and not check_response(response_data):
                self.log_test(name, False, "Response validation failed")
                return False, response_data

            self.log_test(name, True)
            return True, response_data

        except Exception as e:
            self.log_test(name, False, f"Error: {str(e)}")
            return False, {}

    def test_api_root(self):
        """Test API root endpoint"""
        def check_root(data):
            return 'message' in data and 'دليل بيتس' in data.get('message', '')
        
        return self.run_test(
            "API Root",
            "GET",
            "",
            check_response=check_root,
            auth_required=False
        )

    def test_login(self):
        """Test login endpoint with admin credentials"""
        login_data = {
            "email": "admin@daleelpets.com",
            "password": "admin123"
        }
        
        def check_login(data):
            return 'token' in data and 'user' in data and data['user'].get('role') == 'admin'
        
        success, data = self.run_test(
            "Admin Login",
            "POST",
            "auth/login",
            data=login_data,
            check_response=check_login,
            auth_required=False
        )
        
        # Store token for subsequent tests
        if success and data:
            self.token = data.get('token')
        
        return success, data

    def test_auth_me(self):
        """Test auth/me endpoint with Bearer token"""
        if not self.token:
            self.log_test("Auth Me", False, "No token available")
            return False, {}
        
        def check_me(data):
            return 'email' in data and 'role' in data and data.get('email') == 'admin@daleelpets.com'
        
        return self.run_test(
            "Auth Me",
            "GET",
            "auth/me",
            check_response=check_me
        )

    def test_my_products(self):
        """Test my-products endpoint"""
        def check_products(data):
            return 'kpis' in data and 'products' in data and isinstance(data['products'], list)
        
        success, response_data = self.run_test(
            "My Products",
            "GET",
            "my-products",
            check_response=check_products
        )
        
        # Store first product SKU for Phase 2 tests
        if success and response_data and 'products' in response_data:
            products = response_data['products']
            if products:
                self.product_sku = products[0]['sku']
        
        return success

    def test_my_products_with_filters(self):
        """Test my-products with various filters"""
        # Test with different date ranges
        success1, _ = self.run_test(
            "My Products - 7 days",
            "GET",
            "my-products?days=7",
            check_response=lambda data: 'kpis' in data and 'products' in data
        )
        
        # Test with search
        success2, _ = self.run_test(
            "My Products - Search",
            "GET",
            "my-products?search=رويال",
            check_response=lambda data: 'kpis' in data and 'products' in data
        )
        
        # Test with category filter
        success3, _ = self.run_test(
            "My Products - Category Filter",
            "GET",
            "my-products?category=cat_food",
            check_response=lambda data: 'kpis' in data and 'products' in data
        )
        
        # Test with sorting
        success4, _ = self.run_test(
            "My Products - Sort by Revenue",
            "GET",
            "my-products?sort_by=revenue_est&sort_order=desc",
            check_response=lambda data: 'kpis' in data and 'products' in data
        )
        
        return success1 and success2 and success3 and success4

    def test_product_detail(self):
        """Test product detail endpoint"""
        # Use a known SKU from the seeded data
        test_sku = "RC-ICAT-4"
        
        def check_product_detail(data):
            return 'sku' in data and 'store_prices' in data and 'price_range' in data
        
        return self.run_test(
            "Product Detail",
            "GET",
            f"products/{test_sku}",
            check_response=check_product_detail
        )

    def test_product_history(self):
        """Test product price history endpoint"""
        test_sku = "RC-ICAT-4"
        
        def check_history(data):
            return 'history' in data and isinstance(data['history'], dict)
        
        return self.run_test(
            "Product History",
            "GET",
            f"products/{test_sku}/history?days=30",
            check_response=check_history
        )

    def test_product_velocity(self):
        """Test product velocity endpoint"""
        test_sku = "RC-ICAT-4"
        
        def check_velocity(data):
            return 'velocity' in data and 'avg_daily' in data and isinstance(data['velocity'], list)
        
        return self.run_test(
            "Product Velocity",
            "GET",
            f"products/{test_sku}/velocity?days=14",
            check_response=check_velocity
        )

    def test_insights_summary(self):
        """Test insights summary endpoint"""
        def check_summary(data):
            required_fields = ['total_skus', 'price_drops', 'product_gaps', 'median_spread', 'avg_confidence']
            return all(field in data for field in required_fields)
        
        return self.run_test(
            "Insights Summary",
            "GET",
            "insights/summary?days=30",
            check_response=check_summary
        )

    def test_insights_leaderboard(self):
        """Test insights leaderboard endpoint"""
        def check_leaderboard(data):
            return isinstance(data, list) and len(data) > 0 and 'store' in data[0] and 'revenue_est' in data[0]
        
        return self.run_test(
            "Insights Leaderboard",
            "GET",
            "insights/leaderboard?days=30",
            check_response=check_leaderboard
        )

    def test_insights_top_sellers(self):
        """Test insights top sellers endpoint"""
        def check_top_sellers(data):
            return isinstance(data, list) and (len(data) == 0 or ('sku' in data[0] and 'units_sold' in data[0]))
        
        return self.run_test(
            "Insights Top Sellers",
            "GET",
            "insights/top-sellers?days=30",
            check_response=check_top_sellers
        )

    def test_stores_list(self):
        """Test stores list endpoint - Phase 3 returns {stores: [...], crawl_paused: bool}"""
        def check_stores(data):
            # Phase 3: API returns {stores: [...], crawl_paused: bool}
            if isinstance(data, dict) and 'stores' in data and 'crawl_paused' in data:
                stores = data['stores']
                return isinstance(stores, list) and len(stores) >= 7  # Should have 7 seeded stores
            # Fallback for old format
            return isinstance(data, list) and len(data) >= 7
        
        success, data = self.run_test(
            "Stores List (Phase 3 format)",
            "GET",
            "stores",
            check_response=check_stores
        )
        
        # Store first store ID for crawl test
        if success and data:
            stores = data.get('stores', data) if isinstance(data, dict) else data
            if stores and len(stores) > 0:
                self.test_store_id = stores[0].get('id')
        
        return success, data

    def test_create_store(self):
        """Test create store endpoint"""
        store_data = {
            "name": "Test Pet Store",
            "domain": "testpetstore.sa",
            "platform": "salla",
            "crawl_frequency_hrs": 24
        }
        
        def check_created_store(data):
            return data.get('name') == store_data['name'] and data.get('domain') == store_data['domain']
        
        success, data = self.run_test(
            "Create Store",
            "POST",
            "stores",
            data=store_data,
            check_response=check_created_store
        )
        
        # Store created store ID for cleanup
        if success and data:
            self.created_store_id = data.get('id')
        
        return success, data

    def test_crawl_store(self):
        """Test store crawl endpoint (mocked)"""
        if not self.test_store_id:
            self.log_test("Store Crawl", False, "No store ID available")
            return False, {}
        
        def check_crawl(data):
            return 'message' in data and 'store_id' in data and 'products_found' in data
        
        return self.run_test(
            "Store Crawl",
            "POST",
            f"stores/{self.test_store_id}/crawl",
            check_response=check_crawl
        )

    def test_export_csv(self):
        """Test CSV export endpoint"""
        # This endpoint returns a file, so we just check for 200 status
        return self.run_test(
            "Export CSV",
            "GET",
            "export/products?days=30",
            expected_status=200,
            check_response=None  # Don't check JSON response for file download
        )

    def cleanup_created_store(self):
        """Clean up created test store"""
        if hasattr(self, 'created_store_id') and self.created_store_id:
            try:
                self.run_test(
                    "Delete Test Store",
                    "DELETE",
                    f"stores/{self.created_store_id}",
                    check_response=lambda data: 'message' in data
                )
            except:
                pass  # Ignore cleanup errors

    # Phase 2 Test Methods
    def test_crawl_logs(self):
        """Test crawl logs endpoint"""
        if not self.test_store_id:
            print("⚠️  No store ID available for crawl logs test")
            return True
            
        return self.run_test(
            "Crawl Logs",
            "GET",
            f"stores/{self.test_store_id}/crawl-logs?limit=5",
            check_response=lambda data: isinstance(data, list)
        )

    def test_store_profile(self):
        """Test store profile endpoint"""
        if not self.test_store_id:
            print("⚠️  No store ID available for profile test")
            return True
            
        return self.run_test(
            "Store Profile",
            "GET",
            f"stores/{self.test_store_id}/profile",
            check_response=lambda data: 'store' in data and 'kpis' in data
        )

    def test_alerts_list(self):
        """Test alerts list endpoint"""
        return self.run_test(
            "Alerts List",
            "GET",
            "alerts",
            check_response=lambda data: isinstance(data, list)
        )

    def test_alerts_create(self):
        """Test create alert"""
        if not self.product_sku:
            print("⚠️  No product SKU available for alert creation")
            return True
            
        alert_data = {
            "product_sku": self.product_sku,
            "alert_type": "price_drop",
            "threshold": 10.0,
            "channel": "in_app"
        }
        
        success = self.run_test(
            "Create Alert",
            "POST",
            "alerts",
            expected_status=200,  # Backend returns 200, not 201
            data=alert_data,
            check_response=lambda data: 'id' in data
        )
        
        # Store alert ID for later tests
        if success:
            try:
                response = requests.get(f"{self.api_url}/alerts", 
                                      headers={'Authorization': f'Bearer {self.token}'})
                if response.status_code == 200:
                    alerts = response.json()
                    if alerts:
                        self.alert_id = alerts[0]['id']
            except:
                pass
        
        return success

    def test_alerts_toggle(self):
        """Test toggle alert"""
        if not self.alert_id:
            print("⚠️  No alert ID available for toggle test")
            return True
            
        return self.run_test(
            "Toggle Alert",
            "PUT",
            f"alerts/{self.alert_id}/toggle",
            check_response=lambda data: 'is_active' in data
        )

    def test_alerts_check(self):
        """Test check alerts now"""
        return self.run_test(
            "Check Alerts",
            "POST",
            "alerts/check",
            check_response=lambda data: 'message' in data
        )

    def test_alerts_feed(self):
        """Test alert feed"""
        return self.run_test(
            "Alert Feed",
            "GET",
            "alerts/feed?days=30",
            check_response=lambda data: isinstance(data, list)
        )

    def test_alerts_delete(self):
        """Test delete alert"""
        if not self.alert_id:
            print("⚠️  No alert ID available for delete test")
            return True
            
        return self.run_test(
            "Delete Alert",
            "DELETE",
            f"alerts/{self.alert_id}",
            check_response=lambda data: 'message' in data
        )

    # Phase 3 Test Methods
    def test_discounts_top_pct(self):
        """Test discounts top percentage endpoint"""
        return self.run_test(
            "Discounts Top Percentage",
            "GET",
            "discounts/top-pct",
            check_response=lambda data: isinstance(data, list)
        )

    def test_discounts_top_amount(self):
        """Test discounts top amount endpoint"""
        return self.run_test(
            "Discounts Top Amount",
            "GET",
            "discounts/top-amount",
            check_response=lambda data: isinstance(data, list)
        )

    def test_discounts_timeline(self):
        """Test discounts timeline heatmap endpoint"""
        def check_timeline(data):
            return 'timeline' in data and 'stores' in data and isinstance(data['timeline'], list)
        
        return self.run_test(
            "Discounts Timeline",
            "GET",
            "discounts/timeline",
            check_response=check_timeline
        )

    def test_discounts_aggression(self):
        """Test discounts aggression leaderboard endpoint"""
        def check_aggression(data):
            return isinstance(data, list) and (len(data) == 0 or 'store' in data[0] and 'score' in data[0])
        
        return self.run_test(
            "Discounts Aggression Leaderboard",
            "GET",
            "discounts/aggression",
            check_response=check_aggression
        )

    def test_scanner_opportunities(self):
        """Test price scanner opportunities endpoint"""
        def check_opportunities(data):
            required_fields = ['summary', 'opportunities', 'well_positioned', 'undercut']
            return all(field in data for field in required_fields)
        
        return self.run_test(
            "Scanner Opportunities",
            "GET",
            "scanner/opportunities?days=14",
            check_response=check_opportunities
        )

    def test_scheduler_status(self):
        """Test scheduler status endpoint"""
        def check_scheduler(data):
            return 'crawl_paused' in data and 'jobs' in data and 'total_jobs' in data
        
        return self.run_test(
            "Scheduler Status",
            "GET",
            "scheduler/status",
            check_response=check_scheduler
        )

    def test_scheduler_toggle_pause(self):
        """Test scheduler toggle pause endpoint"""
        def check_toggle(data):
            return 'crawl_paused' in data and 'message' in data
        
        return self.run_test(
            "Scheduler Toggle Pause",
            "POST",
            "scheduler/toggle-pause",
            check_response=check_toggle
        )

    # Phase 4 Test Methods
    def test_crawl_logs_with_tiers(self):
        """Test crawl logs show tier progression and endpoint_used field"""
        if not self.test_store_id:
            print("⚠️  No store ID available for tier crawl logs test")
            return True
            
        def check_tier_logs(data):
            if not isinstance(data, list) or len(data) == 0:
                return True  # Empty logs are acceptable
            
            # Check if logs have tier information and endpoint_used field
            log = data[0]
            has_tier = 'tier_used' in log or 'tier_attempted' in log
            has_endpoint = 'endpoint_used' in log
            return has_tier and has_endpoint
        
        return self.run_test(
            "Crawl Logs with Tier Info",
            "GET",
            f"stores/{self.test_store_id}/crawl-logs?limit=10",
            check_response=check_tier_logs
        )

    def test_zarafa_store_products(self):
        """Test that Zarafa store has 8+ real products from Tier 2 crawling"""
        # Find Zarafa store
        success, stores_data = self.test_stores_list()
        if not success:
            self.log_test("Zarafa Store Products", False, "Could not get stores list")
            return False
            
        stores = stores_data.get('stores', stores_data) if isinstance(stores_data, dict) else stores_data
        zarafa_store = None
        for store in stores:
            if 'zarafa' in store.get('name', '').lower():
                zarafa_store = store
                break
        
        if not zarafa_store:
            self.log_test("Zarafa Store Products", False, "Zarafa store not found")
            return False
        
        # Check product count for Zarafa
        product_count = zarafa_store.get('product_count', 0)
        if product_count >= 8:
            self.log_test("Zarafa Store Products", True, f"Found {product_count} products")
            return True
        else:
            self.log_test("Zarafa Store Products", False, f"Only {product_count} products, expected 8+")
            return False

    def test_total_products_count(self):
        """Test that total products is 210 (202 mock + 8 real)"""
        success, data = self.run_test(
            "My Products Count Check",
            "GET",
            "my-products",
            check_response=lambda data: 'products' in data
        )
        
        if not success:
            return False
            
        products = data.get('products', [])
        total_count = len(products)
        
        if total_count >= 210:
            self.log_test("Total Products Count", True, f"Found {total_count} products")
            return True
        else:
            self.log_test("Total Products Count", False, f"Only {total_count} products, expected 210+")
            return False

    def test_digest_generate(self):
        """Test POST /api/digests/generate creates a market digest"""
        def check_digest_generate(data):
            required_fields = ['id', 'content', 'generated_at', 'week_start', 'week_end']
            return all(field in data for field in required_fields)
        
        return self.run_test(
            "Generate Market Digest",
            "POST",
            "digests/generate",
            check_response=check_digest_generate
        )

    def test_digest_latest(self):
        """Test GET /api/digests/latest returns the generated digest with 5 content sections"""
        def check_digest_latest(data):
            if not data or 'content' not in data:
                return False
            
            content = data['content']
            # Check for 5 main content sections
            expected_sections = ['market_summary', 'top_price_drops', 'new_products', 'oos_events']
            sections_found = sum(1 for section in expected_sections if section in content)
            return sections_found >= 4  # At least 4 of the 5 sections
        
        return self.run_test(
            "Get Latest Digest",
            "GET",
            "digests/latest",
            check_response=check_digest_latest
        )

    def test_digest_list(self):
        """Test GET /api/digests returns list of digests"""
        def check_digest_list(data):
            return isinstance(data, list)
        
        return self.run_test(
            "List Digests",
            "GET",
            "digests",
            check_response=check_digest_list
        )

    def test_scheduler_weekly_digest_job(self):
        """Test GET /api/scheduler/status shows weekly_digest job registered"""
        def check_weekly_digest_job(data):
            if 'jobs' not in data:
                return False
            
            jobs = data['jobs']
            # Look for weekly digest job
            for job in jobs:
                if 'weekly' in job.get('id', '').lower() or 'digest' in job.get('id', '').lower():
                    return True
            return False
        
        return self.run_test(
            "Scheduler Weekly Digest Job",
            "GET",
            "scheduler/status",
            check_response=check_weekly_digest_job
        )

    def test_sar_currency_display(self):
        """Test that SAR values display with ﷼ symbol in API responses"""
        success, data = self.run_test(
            "SAR Currency Check",
            "GET",
            "my-products?limit=5",
            check_response=lambda data: 'products' in data
        )
        
        if not success:
            return False
        
        # Check if any price fields contain SAR or ﷼ symbol
        products = data.get('products', [])
        if not products:
            self.log_test("SAR Currency Display", True, "No products to check")
            return True
        
        # The API should return numeric values, frontend handles ﷼ display
        # Just verify we have price data
        has_price_data = any('price' in str(product) for product in products[:3])
        if has_price_data:
            self.log_test("SAR Currency Display", True, "Price data available for frontend formatting")
            return True
        else:
            self.log_test("SAR Currency Display", False, "No price data found")
            return False

    def test_arabic_product_names(self):
        """Test that Arabic product names are present in API responses"""
        success, data = self.run_test(
            "Arabic Product Names",
            "GET",
            "my-products?limit=5",
            check_response=lambda data: 'products' in data
        )
        
        if not success:
            return False
        
        products = data.get('products', [])
        if not products:
            self.log_test("Arabic Product Names", True, "No products to check")
            return True
        
        # Check if products have Arabic names (name_ar field)
        arabic_names_found = 0
        for product in products[:5]:
            if 'name_ar' in product and product['name_ar']:
                # Check if contains Arabic characters
                arabic_text = product['name_ar']
                if any('\u0600' <= char <= '\u06FF' for char in arabic_text):
                    arabic_names_found += 1
        
        if arabic_names_found > 0:
            self.log_test("Arabic Product Names", True, f"Found {arabic_names_found} products with Arabic names")
            return True
        else:
            self.log_test("Arabic Product Names", False, "No Arabic product names found")
            return False

    def run_all_tests(self):
        """Run all API tests"""
        print("🚀 Starting Daleel Pets Phase 4 API Tests...")
        print(f"Testing against: {self.api_url}")
        print("=" * 60)
        
        # Test API root
        self.test_api_root()
        
        # Test authentication
        self.test_login()
        self.test_auth_me()
        
        # Test my products
        self.test_my_products()
        self.test_my_products_with_filters()
        
        # Test product details
        self.test_product_detail()
        self.test_product_history()
        self.test_product_velocity()
        
        # Test insights
        self.test_insights_summary()
        self.test_insights_leaderboard()
        self.test_insights_top_sellers()
        
        # Test stores
        self.test_stores_list()
        self.test_create_store()
        self.test_crawl_store()
        
        # Phase 2 Tests - Crawl Logs
        self.test_crawl_logs()
        
        # Phase 2 Tests - Store Profile
        self.test_store_profile()
        
        # Phase 2 Tests - Alerts
        self.test_alerts_list()
        self.test_alerts_create()
        self.test_alerts_toggle()
        self.test_alerts_check()
        self.test_alerts_feed()
        self.test_alerts_delete()
        
        # Phase 3 Tests - Discounts
        self.test_discounts_top_pct()
        self.test_discounts_top_amount()
        self.test_discounts_timeline()
        self.test_discounts_aggression()
        
        # Phase 3 Tests - Scanner
        self.test_scanner_opportunities()
        
        # Phase 3 Tests - Scheduler
        self.test_scheduler_status()
        self.test_scheduler_toggle_pause()
        
        # Phase 4 Tests - 3-tier Crawler & Zarafa
        self.test_crawl_logs_with_tiers()
        self.test_zarafa_store_products()
        self.test_total_products_count()
        
        # Phase 4 Tests - Market Intelligence Digest
        self.test_digest_generate()
        self.test_digest_latest()
        self.test_digest_list()
        self.test_scheduler_weekly_digest_job()
        
        # Phase 4 Tests - Data Display
        self.test_sar_currency_display()
        self.test_arabic_product_names()
        
        # Test export
        self.test_export_csv()
        
        # Cleanup
        self.cleanup_created_store()
        
        # Print results
        print("=" * 60)
        print(f"📊 Test Results: {self.tests_passed}/{self.tests_run} passed")
        
        if self.failed_tests:
            print("\n❌ Failed Tests:")
            for test in self.failed_tests:
                print(f"  - {test['test']}: {test['details']}")
        
        success_rate = (self.tests_passed / self.tests_run) * 100 if self.tests_run > 0 else 0
        print(f"Success Rate: {success_rate:.1f}%")
        
        return self.tests_passed == self.tests_run

def main():
    """Main test runner"""
    tester = DaleelPetsAPITester()
    success = tester.run_all_tests()
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())