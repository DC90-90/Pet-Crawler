// Admin CMS data layer: auth, generic resource CRUD, and singleton endpoints.
// All hooks use TanStack Query + the shared api() client (cookie auth + CSRF).
import {
  useQuery,
  useMutation,
  useQueryClient,
  keepPreviousData,
} from "@tanstack/react-query";
import { api, ApiError } from "./api";
import type {
  Lang,
  LocalizedText,
  PublishStatus,
  Paginated,
  Navigation,
  Page,
  Cta,
  Media,
} from "./types";

/* ============================================================= *
 *  Small utilities
 * ============================================================= */

/** Resolve a localized value to a display string (falls back to English). */
export function tx(v: LocalizedText | undefined | null, lang: Lang = "en"): string {
  if (!v) return "";
  return v[lang] || v.en || v.ka || v.ar || "";
}

/** Human-readable message from any thrown error. */
export function errMessage(e: unknown): string {
  if (e instanceof ApiError) return e.detail;
  if (e instanceof Error) return e.message;
  return "Something went wrong";
}

function qs(params: Record<string, unknown>): string {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  });
  const s = sp.toString();
  return s ? `?${s}` : "";
}

/* ============================================================= *
 *  Lightweight toast store (rendered by <Toaster/> in AdminLayout)
 * ============================================================= */

export type ToastKind = "success" | "danger" | "warning";
export interface ToastMessage {
  id: number;
  kind: ToastKind;
  message: string;
}

let toastList: ToastMessage[] = [];
let toastSeq = 0;
const toastListeners = new Set<(t: ToastMessage[]) => void>();

function emitToasts() {
  toastListeners.forEach((l) => l(toastList));
}

export function toast(message: string, kind: ToastKind = "success"): void {
  const t: ToastMessage = { id: ++toastSeq, kind, message };
  toastList = [...toastList, t];
  emitToasts();
  setTimeout(() => dismissToast(t.id), 4500);
}

export function dismissToast(id: number): void {
  toastList = toastList.filter((t) => t.id !== id);
  emitToasts();
}

export function subscribeToasts(cb: (t: ToastMessage[]) => void): () => void {
  toastListeners.add(cb);
  cb(toastList);
  return () => {
    toastListeners.delete(cb);
  };
}

/* ============================================================= *
 *  Shared admin document shapes
 * ============================================================= */

export interface Envelope {
  status: PublishStatus;
  publishAt?: string;
  unpublishAt?: string;
  publishedAt?: string;
  createdAt?: string;
  updatedAt?: string;
  createdBy?: string;
  lastEditedBy?: string;
  verificationStatus?: "verified" | "needs_verification";
  isVerified?: boolean;
}

export interface SeoBlock {
  title?: LocalizedText;
  description?: LocalizedText;
  ogImageMediaId?: string;
  noindex?: boolean;
  canonicalPath?: string;
}

export interface AdminTour extends Envelope {
  id: string;
  slug: string;
  name: LocalizedText;
  shortDescription: LocalizedText;
  fullDescription?: LocalizedText;
  coverMediaId?: string;
  galleryMediaIds?: string[];
  promoVideoId?: string;
  destinationIds?: string[];
  categories?: string[];
  durationHours?: number;
  durationDays?: number;
  startLocation?: string;
  endLocation?: string;
  suggestedStartTime?: string;
  walkingDistanceKm?: number;
  drivingDistanceKm?: number;
  elevationGainM?: number;
  maxAltitudeM?: number;
  difficulty?: "easy" | "moderate" | "challenging" | "strenuous";
  fitnessLevel?: string;
  minAge?: number;
  groupSizeMin?: number;
  groupSizeMax?: number;
  tourType?: "private" | "shared" | "custom";
  seasons?: string[];
  weatherDependency?: string;
  accessibilityNotes?: LocalizedText;
  familyFriendly?: boolean;
  lowWalking?: boolean;
  winter?: boolean;
  inclusions?: LocalizedText[];
  exclusions?: LocalizedText[];
  whatToBring?: LocalizedText[];
  itinerary?: { title: LocalizedText; body: LocalizedText }[];
  safetyNotes?: LocalizedText;
  priceDisplay: "amount" | "contact";
  priceAmount?: number;
  currency?: string;
  offerId?: string;
  featured?: boolean;
  displayOrder?: number;
  seo?: SeoBlock;
}

export interface AdminDestination extends Envelope {
  id: string;
  slug: string;
  name: LocalizedText;
  intro: LocalizedText;
  description?: LocalizedText;
  coordinates?: { lat: number; lng: number };
  altitudeM?: number;
  bestSeasons?: string[];
  galleryMediaIds?: string[];
  coverMediaId?: string;
  videoIds?: string[];
  relatedTourIds?: string[];
  culturalNotes?: LocalizedText;
  practicalAdvice?: LocalizedText;
  accessibilityInfo?: LocalizedText;
  safetyNotice?: LocalizedText;
  relatedArticleIds?: string[];
  displayOrder?: number;
  seo?: SeoBlock;
}

export interface AdminArticle extends Envelope {
  id: string;
  slug: string;
  title: LocalizedText;
  excerpt: LocalizedText;
  body?: LocalizedText;
  coverMediaId?: string;
  author?: string;
  categories?: string[];
  tags?: string[];
  relatedTourIds?: string[];
  relatedDestinationIds?: string[];
  readingMinutes?: number;
  seo?: SeoBlock;
}

export interface AdminBanner {
  id: string;
  name: string;
  placement: "announcement" | "hero" | "internal" | "promo";
  title: LocalizedText;
  subtitle?: LocalizedText;
  desktopMediaId?: string;
  mobileMediaId?: string;
  overlayIntensity?: number;
  cta?: Cta;
  pageTargets?: string[];
  languageTargets?: string[];
  priority?: number;
  active: boolean;
  startAt?: string;
  endAt?: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface AdminOffer extends Envelope {
  id: string;
  title: LocalizedText;
  description: LocalizedText;
  code?: string;
  discountType?: "percent" | "fixed" | "display";
  discountValue?: number;
  terms?: LocalizedText;
  relatedTourIds?: string[];
  bannerId?: string;
  cta?: Cta;
  featured?: boolean;
  priority?: number;
  languageTargets?: string[];
  startAt?: string;
  endAt?: string;
}

export interface AdminPopup {
  id: string;
  title: LocalizedText;
  body: LocalizedText;
  mediaId?: string;
  cta?: Cta;
  startAt?: string;
  endAt?: string;
  pageTargets?: string[];
  languageTargets?: string[];
  deviceTargets?: ("desktop" | "mobile")[];
  delaySeconds?: number;
  scrollDepthPercent?: number;
  exitIntent?: boolean;
  audience?: "all" | "new" | "returning";
  frequency:
    | "once_ever"
    | "once_session"
    | "once_day"
    | "every_visit"
    | "custom_days";
  frequencyDays?: number;
  dismissible?: boolean;
  priority?: number;
  active: boolean;
  createdAt?: string;
  updatedAt?: string;
}

export interface AdminReview {
  id: string;
  reviewerName: string;
  country?: string;
  rating: number;
  text: string;
  date?: string;
  tourId?: string;
  source: "manual" | "google" | "tripadvisor" | "other";
  sourceUrl?: string;
  permissionStatus?: "granted" | "pending" | "unknown";
  featured?: boolean;
  published: boolean;
  isSample?: boolean;
  createdAt?: string;
}

export interface AdminFaq {
  id: string;
  question: LocalizedText;
  answer: LocalizedText;
  category: string;
  displayOrder?: number;
  published: boolean;
}

export interface AdminGalleryAlbum {
  id: string;
  title: LocalizedText;
  slug: string;
  category?: string;
  coverMediaId?: string;
  mediaIds?: string[];
  displayOrder?: number;
  published: boolean;
  createdAt?: string;
  updatedAt?: string;
}

export interface AdminVideo {
  id: string;
  title: LocalizedText;
  caption?: LocalizedText;
  kind: "uploaded" | "youtube" | "vimeo";
  mediaId?: string;
  externalUrl?: string;
  posterMediaId?: string;
  featured?: boolean;
  displayOrder?: number;
  published: boolean;
  createdAt?: string;
  updatedAt?: string;
}

export interface AdminRedirect {
  id: string;
  fromPath: string;
  toPath: string;
  statusCode: 301 | 302;
  createdAt?: string;
  createdBy?: string;
}

export interface AdminMedia extends Media {
  storageKey?: string;
  originalFilename?: string;
  sizeBytes?: number;
  collection?: string;
  posterMediaId?: string;
  usageRefs?: { collection: string; docId: string }[];
  archived?: boolean;
  createdAt?: string;
}

export interface AdminUser {
  id: string;
  email: string;
  name?: string;
  role: "owner" | "editor";
  isActive: boolean;
  forcePasswordChange?: boolean;
  lastLoginAt?: string;
  createdAt?: string;
}

export interface Me {
  id: string;
  email: string;
  name?: string;
  role: "owner" | "editor";
  forcePasswordChange?: boolean;
}

export interface AuditLog {
  id: string;
  at: string;
  userId?: string;
  userEmail?: string;
  action: string;
  entity?: string;
  entityId?: string;
  summary?: string;
  ip?: string;
}

export interface Inquiry {
  id: string;
  fullName: string;
  email: string;
  phone?: string;
  country?: string;
  preferredLanguage?: string;
  arrivalDate?: string;
  departureDate?: string;
  flexibleDates?: boolean;
  groupSize?: number;
  children?: number;
  selectedTourId?: string;
  interests?: string[];
  activityLevel?: string;
  needTransport?: boolean;
  pickupLocation?: string;
  accommodationStatus?: string;
  message: string;
  consent?: boolean;
  marketingOptIn?: boolean;
  status:
    | "new"
    | "reviewing"
    | "contacted"
    | "quoted"
    | "confirmed"
    | "completed"
    | "closed"
    | "spam";
  notes?: { authorId: string; text: string; at: string }[];
  timeline?: { type: string; at: string; by?: string; summary?: string }[];
  createdAt?: string;
  updatedAt?: string;
}

export interface AdminSettings {
  brandName: string;
  tagline: LocalizedText;
  logoMediaId?: string;
  faviconMediaId?: string;
  ownerPortraitMediaId?: string;
  aboutText?: LocalizedText;
  contact?: { phone?: string; whatsapp?: string; email?: string; region?: string };
  socials?: { platform: string; url: string }[];
  supportedLanguages?: string[];
  defaultLanguage?: string;
  currency?: string;
  timezone?: string;
  analytics?: { gaId?: string; gscVerification?: string; metaPixelId?: string };
  cookieNotice?: LocalizedText;
  emergencyNotice?: { enabled: boolean; text: LocalizedText };
  globalCta?: Cta;
  seoDefaults?: {
    titlePattern?: string;
    description?: LocalizedText;
    socialImageMediaId?: string;
    canonicalBaseUrl?: string;
    robots?: string;
  };
  updatedAt?: string;
  updatedBy?: string;
}

export interface Overview {
  tours?: { published?: number; draft?: number; total?: number };
  offers?: { active?: number; scheduled?: number };
  popups?: { active?: number };
  inquiries?: { new?: number; total?: number };
  media?: { recent?: number; total?: number };
  needsVerification?: number;
  recentActivity?: AuditLog[];
  // Defensive: the backend may return additional counters.
  [k: string]: unknown;
}

/* ============================================================= *
 *  Auth hooks
 * ============================================================= */

export const meKey = ["admin", "me"] as const;

export function useMe() {
  return useQuery({
    queryKey: meKey,
    queryFn: () => api<Me>("/api/auth/me"),
    retry: false,
    staleTime: 60_000,
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      api<Me | { user: Me }>("/api/auth/login", { method: "POST", body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: meKey });
    },
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<void>("/api/auth/logout", { method: "POST" }),
    onSuccess: () => {
      qc.clear();
    },
  });
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (body: { currentPassword: string; newPassword: string }) =>
      api<void>("/api/auth/change-password", { method: "POST", body }),
    onSuccess: () => toast("Password updated"),
    onError: (e) => toast(errMessage(e), "danger"),
  });
}

/* ============================================================= *
 *  Generic admin resource factory
 * ============================================================= */

export interface ListParams {
  page?: number;
  pageSize?: number;
  q?: string;
  status?: string;
  [k: string]: unknown;
}

export interface ResourceHooks<T> {
  key: readonly unknown[];
  useList: (params?: ListParams) => ReturnType<typeof useQuery<Paginated<T>>>;
  useOne: (id: string) => ReturnType<typeof useQuery<T>>;
  useCreate: () => ReturnType<typeof useMutation<T, unknown, Partial<T>>>;
  useUpdate: () => ReturnType<
    typeof useMutation<T, unknown, { id: string; data: Partial<T> }>
  >;
  useRemove: () => ReturnType<typeof useMutation<void, unknown, string>>;
  usePublish: () => ReturnType<typeof useMutation<T, unknown, string>>;
  useUnpublish: () => ReturnType<typeof useMutation<T, unknown, string>>;
}

function adminResource<T>(name: string, label: string): ResourceHooks<T> {
  const base = `/api/admin/${name}`;
  const key = ["admin", name] as const;

  return {
    key,
    useList: (params: ListParams = {}) =>
      useQuery({
        queryKey: [...key, "list", params],
        queryFn: () => api<Paginated<T>>(`${base}${qs(params)}`),
        placeholderData: keepPreviousData,
      }),

    useOne: (id: string) =>
      useQuery({
        queryKey: [...key, "one", id],
        queryFn: () => api<T>(`${base}/${id}`),
        enabled: !!id && id !== "new",
      }),

    useCreate: () => {
      const qc = useQueryClient();
      return useMutation({
        mutationFn: (data: Partial<T>) =>
          api<T>(base, { method: "POST", body: data }),
        onSuccess: () => {
          qc.invalidateQueries({ queryKey: key });
          toast(`${label} created`);
        },
        onError: (e) => toast(errMessage(e), "danger"),
      });
    },

    useUpdate: () => {
      const qc = useQueryClient();
      return useMutation({
        mutationFn: ({ id, data }: { id: string; data: Partial<T> }) =>
          api<T>(`${base}/${id}`, { method: "PUT", body: data }),
        onSuccess: () => {
          qc.invalidateQueries({ queryKey: key });
          toast(`${label} saved`);
        },
        onError: (e) => toast(errMessage(e), "danger"),
      });
    },

    useRemove: () => {
      const qc = useQueryClient();
      return useMutation({
        mutationFn: (id: string) => api<void>(`${base}/${id}`, { method: "DELETE" }),
        onSuccess: () => {
          qc.invalidateQueries({ queryKey: key });
          toast(`${label} deleted`);
        },
        onError: (e) => toast(errMessage(e), "danger"),
      });
    },

    usePublish: () => {
      const qc = useQueryClient();
      return useMutation({
        mutationFn: (id: string) =>
          api<T>(`${base}/${id}/publish`, { method: "POST" }),
        onSuccess: () => {
          qc.invalidateQueries({ queryKey: key });
          toast(`${label} published`);
        },
        onError: (e) => toast(errMessage(e), "danger"),
      });
    },

    useUnpublish: () => {
      const qc = useQueryClient();
      return useMutation({
        mutationFn: (id: string) =>
          api<T>(`${base}/${id}/unpublish`, { method: "POST" }),
        onSuccess: () => {
          qc.invalidateQueries({ queryKey: key });
          toast(`${label} unpublished`);
        },
        onError: (e) => toast(errMessage(e), "danger"),
      });
    },
  };
}

/* ---- Resource instances ---- */
export const toursApi = adminResource<AdminTour>("tours", "Tour");
export const destinationsApi = adminResource<AdminDestination>(
  "destinations",
  "Destination",
);
export const bannersApi = adminResource<AdminBanner>("banners", "Banner");
export const offersApi = adminResource<AdminOffer>("offers", "Offer");
export const popupsApi = adminResource<AdminPopup>("popups", "Popup");
export const articlesApi = adminResource<AdminArticle>("articles", "Article");
export const reviewsApi = adminResource<AdminReview>("reviews", "Review");
export const faqsApi = adminResource<AdminFaq>("faqs", "FAQ");
export const redirectsApi = adminResource<AdminRedirect>("redirects", "Redirect");
export const videosApi = adminResource<AdminVideo>("videos", "Video");
export const galleryAlbumsApi = adminResource<AdminGalleryAlbum>(
  "gallery-albums",
  "Album",
);

/* ============================================================= *
 *  Dashboard / overview
 * ============================================================= */

export function useOverview() {
  return useQuery({
    queryKey: ["admin", "overview"],
    queryFn: () => api<Overview>("/api/admin/overview"),
  });
}

/* ============================================================= *
 *  Inquiries
 * ============================================================= */

export function useInquiries(filters: ListParams = {}) {
  return useQuery({
    queryKey: ["admin", "inquiries", filters],
    queryFn: () => api<Paginated<Inquiry>>(`/api/admin/inquiries${qs(filters)}`),
    placeholderData: keepPreviousData,
  });
}

export function useUpdateInquiry() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<Inquiry> }) =>
      api<Inquiry>(`/api/admin/inquiries/${id}`, { method: "PUT", body: data }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "inquiries"] });
      toast("Inquiry updated");
    },
    onError: (e) => toast(errMessage(e), "danger"),
  });
}

export const inquiriesExportUrl = "/api/admin/inquiries/export.csv";

/* ============================================================= *
 *  Audit logs
 * ============================================================= */

export function useAuditLogs(params: ListParams = {}) {
  return useQuery({
    queryKey: ["admin", "audit-logs", params],
    queryFn: () => api<Paginated<AuditLog>>(`/api/admin/audit-logs${qs(params)}`),
    placeholderData: keepPreviousData,
  });
}

/* ============================================================= *
 *  Users
 * ============================================================= */

export function useUsers() {
  return useQuery({
    queryKey: ["admin", "users"],
    queryFn: () => api<Paginated<AdminUser> | { items: AdminUser[] }>(
      "/api/admin/users",
    ),
  });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<AdminUser> & { password?: string }) =>
      api<AdminUser>("/api/admin/users", { method: "POST", body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "users"] });
      toast("User created");
    },
    onError: (e) => toast(errMessage(e), "danger"),
  });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<AdminUser> }) =>
      api<AdminUser>(`/api/admin/users/${id}`, { method: "PUT", body: data }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "users"] });
      toast("User updated");
    },
    onError: (e) => toast(errMessage(e), "danger"),
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api<void>(`/api/admin/users/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "users"] });
      toast("User removed");
    },
    onError: (e) => toast(errMessage(e), "danger"),
  });
}

/* ============================================================= *
 *  Settings / Navigation / Pages (singletons)
 * ============================================================= */

export function useSettings() {
  return useQuery({
    queryKey: ["admin", "settings"],
    queryFn: () => api<AdminSettings>("/api/admin/settings"),
  });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<AdminSettings>) =>
      api<AdminSettings>("/api/admin/settings", { method: "PUT", body: data }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "settings"] });
      toast("Settings saved");
    },
    onError: (e) => toast(errMessage(e), "danger"),
  });
}

export function useNavigationAdmin() {
  return useQuery({
    queryKey: ["admin", "navigation"],
    queryFn: () => api<Navigation>("/api/admin/navigation"),
  });
}

export function useUpdateNavigation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Navigation) =>
      api<Navigation>("/api/admin/navigation", { method: "PUT", body: data }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "navigation"] });
      toast("Navigation saved");
    },
    onError: (e) => toast(errMessage(e), "danger"),
  });
}

export function usePage(key: string) {
  return useQuery({
    queryKey: ["admin", "page", key],
    queryFn: () => api<Page>(`/api/admin/pages/${key}`),
  });
}

export function useUpdatePage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ key, data }: { key: string; data: Partial<Page> }) =>
      api<Page>(`/api/admin/pages/${key}`, { method: "PUT", body: data }),
    onSuccess: (_res, vars) => {
      qc.invalidateQueries({ queryKey: ["admin", "page", vars.key] });
      toast("Page saved");
    },
    onError: (e) => toast(errMessage(e), "danger"),
  });
}

/* ============================================================= *
 *  Media library
 * ============================================================= */

export interface MediaFilters {
  q?: string;
  kind?: string;
  tag?: string;
  page?: number;
  pageSize?: number;
  [k: string]: unknown;
}

export const mediaKey = ["admin", "media"] as const;

export function useMediaList(filters: MediaFilters = {}) {
  return useQuery({
    queryKey: [...mediaKey, filters],
    queryFn: () => api<Paginated<AdminMedia>>(`/api/admin/media${qs(filters)}`),
    placeholderData: keepPreviousData,
  });
}

export function useUploadMedia() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (formData: FormData) =>
      api<AdminMedia>("/api/admin/media/upload", {
        method: "POST",
        raw: true,
        body: formData,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: mediaKey });
      toast("Upload complete");
    },
    onError: (e) => toast(errMessage(e), "danger"),
  });
}

export function useRegisterExternalMedia() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { url: string; title?: string; kind?: string }) =>
      api<AdminMedia>("/api/admin/media/external", { method: "POST", body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: mediaKey });
      toast("External media registered");
    },
    onError: (e) => toast(errMessage(e), "danger"),
  });
}

export function useUpdateMedia() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<AdminMedia> }) =>
      api<AdminMedia>(`/api/admin/media/${id}`, { method: "PUT", body: data }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: mediaKey });
      toast("Media updated");
    },
    onError: (e) => toast(errMessage(e), "danger"),
  });
}

export function useDeleteMedia() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api<void>(`/api/admin/media/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: mediaKey });
      toast("Media deleted");
    },
    onError: (e) => toast(errMessage(e), "danger"),
  });
}

/** Resolve a media document's best display URL. */
export function mediaUrl(m: AdminMedia | Media | undefined): string | undefined {
  if (!m) return undefined;
  return (
    m.url ||
    m.variants?.card?.url ||
    m.variants?.thumb?.url ||
    m.variants?.original?.url ||
    m.variants?.hero?.url ||
    m.externalUrl
  );
}
