import {
  QueryClient,
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { useEffect } from "react";
import { api } from "./api";
import type {
  Tour,
  Destination,
  Article,
  Banner,
  Offer,
  Popup,
  Review,
  Faq,
  GalleryItem,
  VideoItem,
  SiteSettings,
  Navigation,
  Page,
} from "./types";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

const qs = (params: Record<string, unknown>) => {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "" && v !== false)
      sp.set(k, String(v));
  });
  const s = sp.toString();
  return s ? `?${s}` : "";
};

/* ---------------- public content hooks ---------------- */
export const useSettings = () =>
  useQuery({
    queryKey: ["settings"],
    queryFn: () => api<SiteSettings>("/api/public/settings"),
  });

export const useNavigation = () =>
  useQuery({
    queryKey: ["navigation"],
    queryFn: () => api<Navigation>("/api/public/navigation"),
  });

export const usePage = (key: string) =>
  useQuery({
    queryKey: ["page", key],
    queryFn: () => api<Page>(`/api/public/pages/${key}`),
  });

export const useTours = (filters: Record<string, unknown> = {}) =>
  useQuery({
    queryKey: ["tours", filters],
    queryFn: () => api<{ items: Tour[] }>(`/api/public/tours${qs(filters)}`),
  });

export const useTour = (slug: string) =>
  useQuery({
    queryKey: ["tour", slug],
    queryFn: () => api<Tour>(`/api/public/tours/${slug}`),
    enabled: !!slug,
  });

export const useDestinations = () =>
  useQuery({
    queryKey: ["destinations"],
    queryFn: () => api<{ items: Destination[] }>("/api/public/destinations"),
  });

export const useDestination = (slug: string) =>
  useQuery({
    queryKey: ["destination", slug],
    queryFn: () => api<Destination>(`/api/public/destinations/${slug}`),
    enabled: !!slug,
  });

export const useArticles = () =>
  useQuery({
    queryKey: ["articles"],
    queryFn: () => api<{ items: Article[] }>("/api/public/articles"),
  });

export const useArticle = (slug: string) =>
  useQuery({
    queryKey: ["article", slug],
    queryFn: () => api<Article>(`/api/public/articles/${slug}`),
    enabled: !!slug,
  });

export const useGallery = () =>
  useQuery({
    queryKey: ["gallery"],
    queryFn: async () => {
      // Backend returns { items, albums }; tolerate either during integration.
      const d = await api<{ items?: GalleryItem[]; albums?: unknown[] }>("/api/public/gallery");
      return { items: d.items ?? [] };
    },
  });

export const useVideos = () =>
  useQuery({
    queryKey: ["videos"],
    queryFn: () => api<{ items: VideoItem[] }>("/api/public/videos"),
  });

export const useOffers = () =>
  useQuery({
    queryKey: ["offers"],
    queryFn: () => api<{ items: Offer[] }>("/api/public/offers"),
  });

export const useReviews = () =>
  useQuery({
    queryKey: ["reviews"],
    queryFn: () => api<{ items: Review[] }>("/api/public/reviews"),
  });

export const useFaqs = () =>
  useQuery({
    queryKey: ["faqs"],
    queryFn: () => api<{ items: Faq[] }>("/api/public/faqs"),
  });

export const useBanners = (path: string, lang: string, device: string) =>
  useQuery({
    queryKey: ["banners", path, lang, device],
    queryFn: () =>
      api<{ items: Banner[] }>(`/api/public/banners${qs({ path, lang, device })}`),
  });

export const usePopups = (
  path: string,
  lang: string,
  device: string,
  visitor: string,
) =>
  useQuery({
    queryKey: ["popups", path, lang, device, visitor],
    queryFn: () =>
      api<{ items: Popup[] }>(
        `/api/public/popups${qs({ path, lang, device, visitor })}`,
      ),
  });

export const useSubmitInquiry = () =>
  useMutation({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    mutationFn: (body: any) =>
      api<{ id: string }>("/api/public/inquiries", { method: "POST", body }),
  });

export const useRecommendTours = () =>
  useMutation({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    mutationFn: (body: any) =>
      api<{ items: Tour[] }>("/api/public/tours/recommend", {
        method: "POST",
        body,
      }),
  });

/* --------- content-version driven invalidation --------- */
export function useContentVersionSync(intervalMs = 45_000) {
  const qc = useQueryClient();
  useEffect(() => {
    let last: number | null = null;
    let alive = true;
    const check = async () => {
      try {
        const { version } = await api<{ version: number }>(
          "/api/public/content-version",
        );
        if (last !== null && version !== last) {
          qc.invalidateQueries();
        }
        last = version;
      } catch {
        /* offline / transient — ignore */
      }
    };
    void check();
    const id = setInterval(() => alive && check(), intervalMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [qc, intervalMs]);
}
