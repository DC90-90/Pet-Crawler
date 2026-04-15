#!/usr/bin/env python3
"""
Backend API Testing for PetTracker - Competitor Monitoring Tool
Tests all API endpoints for dashboard, competitors, products, best sellers, price comparison, and sync functionality
"""

import requests
import sys
import json
from datetime import datetime

class PetTrackerAPITester:
    def __init__(self, base_url="https://saudi-pets-monitor.preview.emergentagent.com"):
        self.base_url = base_url
        self.api_url = f"{base_url}/api"
        self.tests_run = 0
        self.tests_passed = 0
        self.failed_tests = []
        self.competitor_id = None

    def log_test(self, name, success, details=""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {name}")
        else:
            print(f"❌ {name} - {details}")
            self.failed_tests.append({"test": name, "details": details})

    def run_test(self, name, method, endpoint, expected_status=200, data=None, check_response=None):
        """Run a single API test"""
        url = f"{self.api_url}/{endpoint}"
        headers = {'Content-Type': 'application/json'}
        
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
                self.log_test(name, False, f"Expected {expected_status}, got {response.status_code}")
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

    def test_dashboard_overview(self):
        """Test dashboard overview endpoint"""
        def check_overview(data):
            required_fields = ['total_competitors', 'total_products', 'avg_price', 'out_of_stock_count']
            return all(field in data for field in required_fields)
        
        return self.run_test(
            "Dashboard Overview",
            "GET",
            "dashboard/overview",
            check_response=check_overview
        )

    def test_get_competitors(self):
        """Test get competitors endpoint"""
        def check_competitors(data):
            if not isinstance(data, list):
                return False
            # Should have 5 seeded competitors
            if len(data) != 5:
                return False
            # Check required fields
            if data:
                required_fields = ['id', 'name', 'platform', 'status']
                return all(field in data[0] for field in required_fields)
            return True
        
        success, data = self.run_test(
            "Get Competitors",
            "GET",
            "competitors",
            check_response=check_competitors
        )
        
        # Store first competitor ID for later tests
        if success and data:
            self.competitor_id = data[0]['id']
        
        return success, data

    def test_create_competitor(self):
        """Test create competitor endpoint"""
        test_data = {
            "name": "Test Pet Store",
            "platform": "Shopify",
            "website_url": "https://testpetstore.sa"
        }
        
        def check_created(data):
            return data.get('name') == test_data['name'] and data.get('platform') == test_data['platform']
        
        success, data = self.run_test(
            "Create Competitor",
            "POST",
            "competitors",
            expected_status=200,
            data=test_data,
            check_response=check_created
        )
        
        # Store created competitor ID for update/delete tests
        if success and data:
            self.created_competitor_id = data.get('id')
        
        return success, data

    def test_update_competitor(self):
        """Test update competitor endpoint"""
        if not hasattr(self, 'created_competitor_id'):
            self.log_test("Update Competitor", False, "No competitor ID available")
            return False, {}
        
        update_data = {
            "name": "Updated Test Pet Store",
            "platform": "Salla"
        }
        
        def check_updated(data):
            return data.get('name') == update_data['name'] and data.get('platform') == update_data['platform']
        
        return self.run_test(
            "Update Competitor",
            "PUT",
            f"competitors/{self.created_competitor_id}",
            data=update_data,
            check_response=check_updated
        )

    def test_delete_competitor(self):
        """Test delete competitor endpoint"""
        if not hasattr(self, 'created_competitor_id'):
            self.log_test("Delete Competitor", False, "No competitor ID available")
            return False, {}
        
        def check_deleted(data):
            return 'message' in data
        
        return self.run_test(
            "Delete Competitor",
            "DELETE",
            f"competitors/{self.created_competitor_id}",
            check_response=check_deleted
        )

    def test_get_products(self):
        """Test get products endpoint"""
        def check_products(data):
            return 'products' in data and 'total' in data and isinstance(data['products'], list)
        
        return self.run_test(
            "Get Products",
            "GET",
            "products",
            check_response=check_products
        )

    def test_get_products_with_filters(self):
        """Test get products with filters"""
        # Test category filter
        success1, _ = self.run_test(
            "Get Products - Category Filter",
            "GET",
            "products?category=Dog Food",
            check_response=lambda data: 'products' in data
        )
        
        # Test search filter
        success2, _ = self.run_test(
            "Get Products - Search Filter",
            "GET",
            "products?search=Royal",
            check_response=lambda data: 'products' in data
        )
        
        # Test sorting
        success3, _ = self.run_test(
            "Get Products - Sort by Price",
            "GET",
            "products?sort_by=price&sort_order=desc",
            check_response=lambda data: 'products' in data
        )
        
        return success1 and success2 and success3

    def test_get_product_categories(self):
        """Test get product categories endpoint"""
        def check_categories(data):
            return isinstance(data, list) and len(data) > 0
        
        return self.run_test(
            "Get Product Categories",
            "GET",
            "products/categories",
            check_response=check_categories
        )

    def test_get_best_sellers(self):
        """Test get best sellers endpoint"""
        def check_best_sellers(data):
            return isinstance(data, list)
        
        return self.run_test(
            "Get Best Sellers",
            "GET",
            "products/best-sellers",
            check_response=check_best_sellers
        )

    def test_get_price_comparison(self):
        """Test get price comparison endpoint"""
        def check_price_comparison(data):
            return 'comparison' in data and 'competitors' in data and isinstance(data['comparison'], list)
        
        return self.run_test(
            "Get Price Comparison",
            "GET",
            "products/price-comparison",
            check_response=check_price_comparison
        )

    def test_sync_competitor(self):
        """Test sync individual competitor"""
        if not self.competitor_id:
            self.log_test("Sync Competitor", False, "No competitor ID available")
            return False, {}
        
        def check_sync(data):
            return 'message' in data and 'competitor_id' in data
        
        return self.run_test(
            "Sync Individual Competitor",
            "POST",
            f"sync/trigger/{self.competitor_id}",
            check_response=check_sync
        )

    def test_sync_all_competitors(self):
        """Test sync all competitors"""
        def check_sync_all(data):
            return 'message' in data and 'last_synced' in data
        
        return self.run_test(
            "Sync All Competitors",
            "POST",
            "sync/trigger-all",
            check_response=check_sync_all
        )

    def test_api_root(self):
        """Test API root endpoint"""
        def check_root(data):
            return 'message' in data
        
        return self.run_test(
            "API Root",
            "GET",
            "",
            check_response=check_root
        )

    def run_all_tests(self):
        """Run all API tests"""
        print("🚀 Starting PetTracker API Tests...")
        print(f"Testing against: {self.api_url}")
        print("=" * 60)
        
        # Test API root
        self.test_api_root()
        
        # Test dashboard
        self.test_dashboard_overview()
        
        # Test competitors
        self.test_get_competitors()
        self.test_create_competitor()
        self.test_update_competitor()
        self.test_delete_competitor()
        
        # Test products
        self.test_get_products()
        self.test_get_products_with_filters()
        self.test_get_product_categories()
        self.test_get_best_sellers()
        self.test_get_price_comparison()
        
        # Test sync functionality (mocked)
        self.test_sync_competitor()
        self.test_sync_all_competitors()
        
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
    tester = PetTrackerAPITester()
    success = tester.run_all_tests()
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())