import { createContext, useContext, useState, useCallback } from "react";

// Local translation dictionary — no external translation API is used.
// To integrate a translation service (e.g., i18next-http-backend), add REACT_APP_I18N_KEY to .env
// and configure the backend plugin here.
const translations = {
  en: {
    app_name: "Daleel Pets", app_name_ar: "دليل بيتس", subtitle: "KSA Pet Market Intelligence",
    nav_products: "My Products", nav_insights: "Insights", nav_scanner: "Price Scanner", nav_discounts: "Discounts", nav_alerts: "Alerts", nav_stores: "Stores", nav_login: "Login",
    kpi_products: "Products Tracked", kpi_units_sold: "Units Sold (Est.)", kpi_revenue: "Revenue (Est.)", kpi_market_share: "Avg. Market Share",
    kpi_skus: "SKUs Tracked", kpi_drops: "Price Drops", kpi_gaps: "Product Gaps", kpi_confidence: "Avg. Confidence", kpi_spread: "Median Spread",
    col_product: "Product", col_sku: "SKU", col_price: "Price", col_vs_low: "vs Lowest", col_vs_med: "vs Median",
    col_sales: "Est. Sales", col_revenue: "Revenue", col_market: "Mkt Size", col_share: "Share %",
    col_sellers: "Sellers", col_stock: "Stock", col_confidence: "Conf.", col_category: "Category",
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
  },
  ar: {
    app_name: "دليل بيتس", app_name_ar: "Daleel Pets", subtitle: "استخبارات سوق الحيوانات الأليفة السعودي",
    nav_products: "منتجاتي", nav_insights: "الرؤى", nav_scanner: "ماسح الأسعار", nav_discounts: "التخفيضات", nav_alerts: "التنبيهات", nav_stores: "المتاجر", nav_login: "دخول",
    kpi_products: "المنتجات المتتبعة", kpi_units_sold: "الوحدات المباعة (تقدير)", kpi_revenue: "الإيرادات (تقدير)", kpi_market_share: "متوسط حصة السوق",
    kpi_skus: "المنتجات المتتبعة", kpi_drops: "انخفاض الأسعار", kpi_gaps: "فجوات المنتجات", kpi_confidence: "متوسط الثقة", kpi_spread: "الانتشار الوسيط",
    col_product: "المنتج", col_sku: "رمز المنتج", col_price: "السعر", col_vs_low: "مقابل الأقل", col_vs_med: "مقابل الوسيط",
    col_sales: "المبيعات", col_revenue: "الإيرادات", col_market: "حجم السوق", col_share: "الحصة %",
    col_sellers: "البائعون", col_stock: "المخزون", col_confidence: "الثقة", col_category: "الفئة",
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
