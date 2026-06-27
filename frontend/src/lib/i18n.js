import { createContext, useContext, useState, useCallback } from "react";

// Local translation dictionary — no external translation API is used.
// To integrate a translation service (e.g., i18next-http-backend), add REACT_APP_I18N_KEY to .env
// and configure the backend plugin here.
const translations = {
  en: {
    app_name: "Daleel", app_name_ar: "دليل", subtitle: "Saudi Market Intelligence Platform",
    tagline: "Track prices, inventory, and competitors across all Saudi online stores in real-time.",
    tagline_short: "Saudi Market, Decoded",
    nav_products: "My Products", nav_insights: "Insights", nav_scanner: "Price Scanner", nav_discounts: "Discounts", nav_alerts: "Alerts", nav_stores: "Stores", nav_import: "Import", nav_priceintel: "Price Intel", nav_login: "Login",
    kpi_products: "Products Tracked", kpi_units_sold: "Units Sold (Est.)", kpi_revenue: "Revenue (Est.)", kpi_market_share: "Avg. Market Share",
    kpi_skus: "SKUs Tracked", kpi_drops: "Price Drops", kpi_gaps: "Product Gaps", kpi_confidence: "Avg. Confidence", kpi_spread: "Median Spread",
    col_product: "Product", col_sku: "SKU", col_price: "My Price", col_vs_low: "vs My Price", col_vs_med: "vs Median",
    col_sales: "Mkt. Sales (Est.)", col_revenue: "Mkt. Revenue (Est.)", col_market: "Mkt Size", col_share: "Share %",
    col_sellers: "Competitors", col_stock: "My Stock", col_confidence: "Conf.", col_category: "Category",
    col_platform: "Platform", col_status: "Status", col_last_crawled: "Last Crawled", col_actions: "Actions",
    col_domain: "Domain", col_frequency: "Frequency", col_products_count: "Products",
    btn_add_store: "Add Store", btn_export: "Export CSV", btn_crawl: "Crawl Now", btn_login: "Login",
    btn_register: "Register", btn_save: "Save", btn_cancel: "Cancel", btn_delete: "Delete",
    chart_leaderboard: "Revenue Leaderboard", chart_top_sellers: "Top Sellers", chart_trending: "Trending",
    chart_price_wars: "Price Wars", chart_restock: "Restock Opportunities", chart_price_history: "Price History",
    chart_velocity: "Daily Velocity", chart_gaps: "Product Gaps",
    d7: "7D", d14: "14D", d30: "30D", d90: "90D",
    stock_high: "HIGH", stock_medium: "MED", stock_low: "LOW", stock_oos: "OOS",
    search: "Search products...", all_categories: "All Categories", all_stores: "All Stores",
    no_data: "No data available", loading: "Loading...",
    tier_label: "Tier", confidence_label: "Confidence",
    price_range: "Price Range", market_avg: "Market Avg", total_volume: "Total Volume",
    stores_carrying: "Stores Carrying", units_day: "units/day",
    email: "Email", password: "Password", name: "Name",
    no_account: "Don't have an account?", has_account: "Already have an account?",
    lang_switch: "العربية", logout: "Logout",
    sar: "SAR", store_name: "Store Name", crawl_frequency: "Crawl Freq (hrs)",
    sales_insights_title: "Product Sales Insights",
    sales_insights_subtitle: "Per-product units sold, revenue, and brand market share for the selected period",
    si_kpi_total_units: "Total Units Sold (Est.)",
    si_kpi_total_revenue: "Total Revenue (Est.)",
    si_kpi_avg_revenue: "Avg. Revenue / Product",
    si_kpi_top_brand: "Top Selling Brand",
    si_top_brands: "Top Brands by Revenue",
    si_col_brand: "Brand",
    si_col_units: "Units Sold",
    si_col_revenue: "Revenue",
    si_col_share: "Market Share",
    si_col_avg_price: "Avg. Price",
    si_search_placeholder: "Search by product, SKU or brand…",
    si_sort_revenue_desc: "Highest Revenue",
    si_sort_revenue_asc: "Lowest Revenue",
    si_sort_sales_desc: "Highest Sales",
    si_sort_sales_asc: "Lowest Sales",
    si_date_from: "From",
    si_date_to: "To",
    si_clear_range: "Clear",
    si_no_data: "No sales data for the selected period.",
  },
  ar: {
    app_name: "دليل", app_name_ar: "Daleel", subtitle: "منصة استخبارات السوق السعودي",
    tagline: "تتبع الأسعار والمخزون والمنافسين عبر جميع المتاجر الإلكترونية السعودية في الوقت الفعلي.",
    tagline_short: "السوق السعودي، مفكّك",
    nav_products: "منتجاتي", nav_insights: "الرؤى", nav_scanner: "ماسح الأسعار", nav_discounts: "التخفيضات", nav_alerts: "التنبيهات", nav_stores: "المتاجر", nav_import: "استيراد", nav_priceintel: "استخبارات الأسعار", nav_login: "دخول",
    kpi_products: "المنتجات المتتبعة", kpi_units_sold: "الوحدات المباعة (تقدير)", kpi_revenue: "الإيرادات (تقدير)", kpi_market_share: "متوسط حصة السوق",
    kpi_skus: "المنتجات المتتبعة", kpi_drops: "انخفاض الأسعار", kpi_gaps: "فجوات المنتجات", kpi_confidence: "متوسط الثقة", kpi_spread: "الانتشار الوسيط",
    col_product: "المنتج", col_sku: "رمز المنتج", col_price: "سعري", col_vs_low: "مقابل سعري", col_vs_med: "مقابل الوسيط",
    col_sales: "مبيعات السوق (تقدير)", col_revenue: "إيرادات السوق (تقدير)", col_market: "حجم السوق", col_share: "الحصة %",
    col_sellers: "المنافسون", col_stock: "مخزوني", col_confidence: "الثقة", col_category: "الفئة",
    col_platform: "المنصة", col_status: "الحالة", col_last_crawled: "آخر زحف", col_actions: "الإجراءات",
    col_domain: "النطاق", col_frequency: "التكرار", col_products_count: "المنتجات",
    btn_add_store: "إضافة متجر", btn_export: "تصدير CSV", btn_crawl: "زحف الآن", btn_login: "تسجيل الدخول",
    btn_register: "إنشاء حساب", btn_save: "حفظ", btn_cancel: "إلغاء", btn_delete: "حذف",
    chart_leaderboard: "ترتيب الإيرادات", chart_top_sellers: "الأكثر مبيعاً", chart_trending: "الرائج",
    chart_price_wars: "حروب الأسعار", chart_restock: "فرص إعادة التخزين", chart_price_history: "تاريخ الأسعار",
    chart_velocity: "السرعة اليومية", chart_gaps: "فجوات المنتجات",
    d7: "7 أيام", d14: "14 يوم", d30: "30 يوم", d90: "90 يوم",
    stock_high: "مرتفع", stock_medium: "متوسط", stock_low: "منخفض", stock_oos: "نفذ",
    search: "ابحث عن المنتجات...", all_categories: "جميع الفئات", all_stores: "جميع المتاجر",
    no_data: "لا توجد بيانات", loading: "جار التحميل...",
    tier_label: "المستوى", confidence_label: "الثقة",
    price_range: "نطاق السعر", market_avg: "متوسط السوق", total_volume: "الحجم الكلي",
    stores_carrying: "متاجر تبيع", units_day: "وحدة/يوم",
    email: "البريد الإلكتروني", password: "كلمة المرور", name: "الاسم",
    no_account: "ليس لديك حساب؟", has_account: "لديك حساب بالفعل؟",
    lang_switch: "English", logout: "خروج",
    sar: "ر.س", store_name: "اسم المتجر", crawl_frequency: "تكرار الزحف (ساعة)",
    sales_insights_title: "رؤى مبيعات المنتجات",
    sales_insights_subtitle: "الوحدات المباعة والإيرادات وحصة العلامة التجارية لكل منتج خلال الفترة المحددة",
    si_kpi_total_units: "إجمالي الوحدات المباعة (تقدير)",
    si_kpi_total_revenue: "إجمالي الإيرادات (تقدير)",
    si_kpi_avg_revenue: "متوسط الإيراد لكل منتج",
    si_kpi_top_brand: "العلامة التجارية الأعلى مبيعاً",
    si_top_brands: "أعلى العلامات التجارية إيراداً",
    si_col_brand: "العلامة التجارية",
    si_col_units: "الوحدات المباعة",
    si_col_revenue: "الإيرادات",
    si_col_share: "حصة السوق",
    si_col_avg_price: "متوسط السعر",
    si_search_placeholder: "ابحث بالمنتج أو الرمز أو العلامة التجارية…",
    si_sort_revenue_desc: "الأعلى إيراداً",
    si_sort_revenue_asc: "الأقل إيراداً",
    si_sort_sales_desc: "الأعلى مبيعاً",
    si_sort_sales_asc: "الأقل مبيعاً",
    si_date_from: "من",
    si_date_to: "إلى",
    si_clear_range: "مسح",
    si_no_data: "لا توجد بيانات مبيعات للفترة المحددة.",
  },
};

const I18nContext = createContext();

export function I18nProvider({ children }) {
  const [lang, setLang] = useState(() => localStorage.getItem("daleel_lang") || "en");

  const t = useCallback((key) => translations[lang]?.[key] || translations.en[key] || key, [lang]);

  const toggleLang = useCallback(() => {
    const next = lang === "en" ? "ar" : "en";
    setLang(next);
    localStorage.setItem("daleel_lang", next);
    document.documentElement.dir = next === "ar" ? "rtl" : "ltr";
    document.documentElement.lang = next;
  }, [lang]);

  const isRTL = lang === "ar";

  return (
    <I18nContext.Provider value={{ lang, t, toggleLang, isRTL }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n() {
  return useContext(I18nContext);
}
