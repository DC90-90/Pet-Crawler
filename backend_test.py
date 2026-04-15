#!/usr/bin/env python3
"""
Daleel Pets Phase 2 Backend API Testing
Tests all endpoints including new Phase 2 features:
- Tier 1 crawler with real HTTP calls
- Alerts CRUD operations
- Store profiles and competitor analysis
- Crawl logs and status tracking
"""

import requests
import sys
import json
from datetime import datetime

class DaleelPetsAPITester:
    def __init__(self, base_url="https://saudi-pets-monitor.preview.emergentagent.com"):
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
        """Test stores list endpoint"""
        def check_stores(data):
            return isinstance(data, list) and len(data) >= 7  # Should have 7 seeded stores
        
        success, data = self.run_test(
            "Stores List",
            "GET",
            "stores",
            check_response=check_stores
        )
        
        # Store first store ID for crawl test
        if success and data and len(data) > 0:
            self.test_store_id = data[0].get('id')
        
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

    def run_all_tests(self):
        """Run all API tests"""
        print("🚀 Starting Daleel Pets API Tests...")
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