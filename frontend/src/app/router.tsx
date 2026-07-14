import { createBrowserRouter, redirect } from "react-router-dom";
import { SUPPORTED_LANGS } from "@/i18n";
import { PublicLayout } from "./PublicLayout";
import { LangLayout } from "./LangLayout";

const detectLang = () => {
  const saved = localStorage.getItem("i18nextLng");
  const nav = navigator.language.split("-")[0];
  const candidate = (saved || nav) as string;
  return SUPPORTED_LANGS.includes(candidate as never) ? candidate : "en";
};

export const router = createBrowserRouter([
  {
    path: "/",
    loader: () => redirect(`/${detectLang()}`),
  },
  {
    path: "/:lang",
    element: <LangLayout />,
    children: [
      {
        element: <PublicLayout />,
        children: [
          { index: true, lazy: () => import("@/pages/public/HomePage") },
          { path: "tours", lazy: () => import("@/pages/public/ToursPage") },
          { path: "tours/:slug", lazy: () => import("@/pages/public/TourDetailPage") },
          { path: "destinations", lazy: () => import("@/pages/public/DestinationsPage") },
          {
            path: "destinations/:slug",
            lazy: () => import("@/pages/public/DestinationDetailPage"),
          },
          { path: "experiences", lazy: () => import("@/pages/public/ExperiencesPage") },
          { path: "about-georgie", lazy: () => import("@/pages/public/AboutPage") },
          { path: "gallery", lazy: () => import("@/pages/public/GalleryPage") },
          { path: "videos", lazy: () => import("@/pages/public/VideosPage") },
          { path: "offers", lazy: () => import("@/pages/public/OffersPage") },
          { path: "travel-guide", lazy: () => import("@/pages/public/TravelGuidePage") },
          {
            path: "travel-guide/:slug",
            lazy: () => import("@/pages/public/ArticlePage"),
          },
          { path: "reviews", lazy: () => import("@/pages/public/ReviewsPage") },
          { path: "plan-your-trip", lazy: () => import("@/pages/public/PlanTripPage") },
          { path: "contact", lazy: () => import("@/pages/public/ContactPage") },
          { path: "inquiry", lazy: () => import("@/pages/public/InquiryPage") },
          { path: "privacy", lazy: () => import("@/pages/public/PrivacyPage") },
          { path: "terms", lazy: () => import("@/pages/public/TermsPage") },
          {
            path: "design-system",
            lazy: () => import("@/pages/public/DesignSystemPage"),
          },
          { path: "*", lazy: () => import("@/pages/public/NotFoundPage") },
        ],
      },
    ],
  },
  {
    path: "/admin/login",
    lazy: () => import("@/pages/admin/LoginPage"),
  },
  {
    path: "/admin",
    lazy: () => import("@/app/AdminLayout"),
    children: [
      { index: true, lazy: () => import("@/pages/admin/OverviewPage") },
      { path: "pages", lazy: () => import("@/pages/admin/PagesPage") },
      { path: "tours", lazy: () => import("@/pages/admin/ToursAdminPage") },
      { path: "tours/:id", lazy: () => import("@/pages/admin/TourEditPage") },
      { path: "destinations", lazy: () => import("@/pages/admin/DestinationsAdminPage") },
      { path: "media", lazy: () => import("@/pages/admin/MediaPage") },
      { path: "banners", lazy: () => import("@/pages/admin/BannersPage") },
      { path: "offers", lazy: () => import("@/pages/admin/OffersPage") },
      { path: "popups", lazy: () => import("@/pages/admin/PopupsPage") },
      { path: "gallery", lazy: () => import("@/pages/admin/GalleryAdminPage") },
      { path: "videos", lazy: () => import("@/pages/admin/VideosAdminPage") },
      { path: "articles", lazy: () => import("@/pages/admin/ArticlesPage") },
      { path: "reviews", lazy: () => import("@/pages/admin/ReviewsPage") },
      { path: "faqs", lazy: () => import("@/pages/admin/FaqsPage") },
      { path: "inquiries", lazy: () => import("@/pages/admin/InquiriesPage") },
      { path: "navigation", lazy: () => import("@/pages/admin/NavigationPage") },
      { path: "seo", lazy: () => import("@/pages/admin/SeoPage") },
      { path: "settings", lazy: () => import("@/pages/admin/SettingsPage") },
      { path: "users", lazy: () => import("@/pages/admin/UsersPage") },
      { path: "audit", lazy: () => import("@/pages/admin/AuditPage") },
    ],
  },
]);
