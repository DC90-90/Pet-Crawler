import type { Option } from "./FormField";

export const STATUS_OPTIONS: Option[] = [
  { value: "draft", label: "Draft" },
  { value: "scheduled", label: "Scheduled" },
  { value: "published", label: "Published" },
  { value: "archived", label: "Archived" },
];

export const STATUS_FILTER_OPTIONS: Option[] = [
  { value: "", label: "All statuses" },
  ...STATUS_OPTIONS,
];

export const DIFFICULTY_OPTIONS: Option[] = [
  { value: "easy", label: "Easy" },
  { value: "moderate", label: "Moderate" },
  { value: "challenging", label: "Challenging" },
  { value: "strenuous", label: "Strenuous" },
];

export const TOUR_TYPE_OPTIONS: Option[] = [
  { value: "private", label: "Private" },
  { value: "shared", label: "Shared" },
  { value: "custom", label: "Custom" },
];

export const PRICE_DISPLAY_OPTIONS: Option[] = [
  { value: "amount", label: "Show amount" },
  { value: "contact", label: "Contact for price" },
];

export const SEASON_OPTIONS: Option[] = [
  { value: "spring", label: "Spring" },
  { value: "summer", label: "Summer" },
  { value: "autumn", label: "Autumn" },
  { value: "winter", label: "Winter" },
];

export const BANNER_PLACEMENT_OPTIONS: Option[] = [
  { value: "announcement", label: "Announcement" },
  { value: "hero", label: "Hero" },
  { value: "internal", label: "Internal" },
  { value: "promo", label: "Promo" },
];

export const DISCOUNT_TYPE_OPTIONS: Option[] = [
  { value: "percent", label: "Percent" },
  { value: "fixed", label: "Fixed amount" },
  { value: "display", label: "Display only" },
];

export const POPUP_FREQUENCY_OPTIONS: Option[] = [
  { value: "once_ever", label: "Once ever" },
  { value: "once_session", label: "Once per session" },
  { value: "once_day", label: "Once per day" },
  { value: "every_visit", label: "Every visit" },
  { value: "custom_days", label: "Custom days" },
];

export const AUDIENCE_OPTIONS: Option[] = [
  { value: "all", label: "All visitors" },
  { value: "new", label: "New visitors" },
  { value: "returning", label: "Returning visitors" },
];

export const REVIEW_SOURCE_OPTIONS: Option[] = [
  { value: "manual", label: "Manual" },
  { value: "google", label: "Google" },
  { value: "tripadvisor", label: "TripAdvisor" },
  { value: "other", label: "Other" },
];

export const VIDEO_KIND_OPTIONS: Option[] = [
  { value: "uploaded", label: "Uploaded" },
  { value: "youtube", label: "YouTube" },
  { value: "vimeo", label: "Vimeo" },
];

export const INQUIRY_STATUS_OPTIONS: Option[] = [
  { value: "new", label: "New" },
  { value: "reviewing", label: "Reviewing" },
  { value: "contacted", label: "Contacted" },
  { value: "quoted", label: "Quoted" },
  { value: "confirmed", label: "Confirmed" },
  { value: "completed", label: "Completed" },
  { value: "closed", label: "Closed" },
  { value: "spam", label: "Spam" },
];

export const INQUIRY_STATUS_FILTER: Option[] = [
  { value: "", label: "All inquiries" },
  ...INQUIRY_STATUS_OPTIONS,
];

export const LANG_OPTIONS: Option[] = [
  { value: "en", label: "English" },
  { value: "ka", label: "Georgian" },
  { value: "ar", label: "Arabic" },
];
