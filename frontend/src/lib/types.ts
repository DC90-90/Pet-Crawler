// Domain types mirroring backend contract (docs/DATA_MODEL.md).
// Kept intentionally lean — only what the UI consumes.

export type Lang = "en" | "ka" | "ar";
export type LocalizedText = Partial<Record<Lang, string>> & { en: string };

export type PublishStatus = "draft" | "scheduled" | "published" | "archived";

export interface Cta {
  label: LocalizedText;
  href: string;
}

export interface MediaVariant {
  url: string;
  w?: number;
  h?: number;
}
export interface Media {
  id: string;
  kind: "image" | "video" | "external_video";
  provider: string;
  externalUrl?: string;
  mimeType?: string;
  width?: number;
  height?: number;
  durationSeconds?: number;
  altText?: LocalizedText;
  caption?: LocalizedText;
  credit?: string;
  location?: string;
  tags?: string[];
  variants?: Record<string, MediaVariant>;
  url?: string; // convenience resolved url
}

export interface SeoBlock {
  title?: LocalizedText;
  description?: LocalizedText;
  ogImageUrl?: string;
  noindex?: boolean;
  canonicalPath?: string;
}

export interface Tour {
  id: string;
  slug: string;
  status: PublishStatus;
  name: LocalizedText;
  shortDescription: LocalizedText;
  fullDescription?: LocalizedText;
  coverUrl?: string;
  galleryUrls?: string[];
  destinationIds?: string[];
  categories?: string[];
  durationHours?: number;
  durationDays?: number;
  startLocation?: string;
  endLocation?: string;
  maxAltitudeM?: number;
  elevationGainM?: number;
  difficulty?: "easy" | "moderate" | "challenging" | "strenuous";
  minAge?: number;
  groupSizeMax?: number;
  tourType?: "private" | "shared" | "custom";
  seasons?: string[];
  familyFriendly?: boolean;
  lowWalking?: boolean;
  winter?: boolean;
  inclusions?: LocalizedText[];
  exclusions?: LocalizedText[];
  whatToBring?: LocalizedText[];
  itinerary?: { title: LocalizedText; body: LocalizedText }[];
  accessibilityNotes?: LocalizedText;
  safetyNotes?: LocalizedText;
  priceDisplay: "amount" | "contact";
  priceAmount?: number;
  currency?: string;
  featured?: boolean;
  verificationStatus?: "verified" | "needs_verification";
}

export interface Destination {
  id: string;
  slug: string;
  name: LocalizedText;
  intro: LocalizedText;
  description?: LocalizedText;
  coordinates?: { lat: number; lng: number };
  altitudeM?: number;
  bestSeasons?: string[];
  galleryUrls?: string[];
  coverUrl?: string;
  culturalNotes?: LocalizedText;
  practicalAdvice?: LocalizedText;
  relatedTourIds?: string[];
}

export interface Article {
  id: string;
  slug: string;
  status: PublishStatus;
  title: LocalizedText;
  excerpt: LocalizedText;
  body?: LocalizedText;
  coverUrl?: string;
  author?: string;
  categories?: string[];
  readingMinutes?: number;
  publishedAt?: string;
  verificationStatus?: string;
}

export interface Banner {
  id: string;
  placement: "announcement" | "hero" | "internal" | "promo";
  title: LocalizedText;
  subtitle?: LocalizedText;
  desktopUrl?: string;
  mobileUrl?: string;
  overlayIntensity?: number;
  cta?: Cta;
}

export interface Offer {
  id: string;
  title: LocalizedText;
  description: LocalizedText;
  code?: string;
  discountType?: "percent" | "fixed" | "display";
  discountValue?: number;
  terms?: LocalizedText;
  cta?: Cta;
  featured?: boolean;
}

export interface Popup {
  id: string;
  title: LocalizedText;
  body: LocalizedText;
  mediaUrl?: string;
  cta?: Cta;
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
}

export interface Review {
  id: string;
  reviewerName: string;
  country?: string;
  rating: number;
  text: string;
  date?: string;
  source?: string;
  isSample?: boolean;
  featured?: boolean;
}

export interface Faq {
  id: string;
  question: LocalizedText;
  answer: LocalizedText;
  category: string;
}

export interface GalleryItem {
  id: string;
  url: string;
  thumbUrl?: string;
  altText?: LocalizedText;
  caption?: LocalizedText;
  location?: string;
  credit?: string;
  category?: string;
  width?: number;
  height?: number;
}

export interface VideoItem {
  id: string;
  title: LocalizedText;
  caption?: LocalizedText;
  kind: "uploaded" | "youtube" | "vimeo";
  url?: string;
  externalUrl?: string;
  posterUrl?: string;
  featured?: boolean;
}

export interface SiteSettings {
  brandName: string;
  tagline: LocalizedText;
  logoUrl?: string;
  ownerPortraitUrl?: string;
  aboutText?: LocalizedText;
  contact?: { phone?: string; whatsapp?: string; email?: string; region?: string };
  socials?: { platform: string; url: string }[];
  supportedLanguages: Lang[];
  defaultLanguage: Lang;
  currency?: string;
  emergencyNotice?: { enabled: boolean; text: LocalizedText };
  globalCta?: Cta;
}

export interface NavLink {
  label: LocalizedText;
  href: string;
  children?: NavLink[];
}
export interface Navigation {
  mainMenu: NavLink[];
  footerGroups: { title: LocalizedText; links: { label: LocalizedText; href: string }[] }[];
  socialLinks?: { platform: string; url: string }[];
  legalLinks?: { label: LocalizedText; href: string }[];
  ctaButton?: Cta;
}

export type SectionType =
  | "hero"
  | "richtext"
  | "split"
  | "tourGrid"
  | "destinationGrid"
  | "gallery"
  | "video"
  | "testimonials"
  | "offers"
  | "faq"
  | "map"
  | "stats"
  | "cta"
  | "contactForm"
  | "announcement"
  | "logoStrip"
  | "seasonalCards";

export interface PageSection {
  id: string;
  type: SectionType;
  hidden?: boolean;
  order: number;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: Record<string, any>;
}
export interface Page {
  key: string;
  title: string;
  sections: PageSection[];
}

export interface Paginated<T> {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
}
