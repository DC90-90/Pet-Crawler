# Data Model — Svaneti with Georgie

MongoDB database (default `svaneti`). No binary media is stored in Mongo — only
metadata. All documents use a string `_id` (uuid4) exposed as `id`. Timestamps
are UTC ISO-8601. Localized text fields use the shape
`{ "en": "...", "ka": "...", "ar": "..." }` (English required; others optional).

## Conventions

- `LocalizedText = { en: string; ka?: string; ar?: string }`
- Publishable documents share a **publishing envelope**:
  - `status: "draft" | "scheduled" | "published" | "archived"`
  - `publishAt?: datetime`, `unpublishAt?: datetime`
  - `publishedAt?: datetime`, `createdAt`, `updatedAt`
  - `createdBy`, `lastEditedBy` (user id)
  - `verificationStatus: "verified" | "needs_verification"`, `isVerified: bool`
- **Effective public visibility** = `status == "published"` AND
  (`publishAt` is null or ≤ now) AND (`unpublishAt` is null or > now).
  Computed server-side; drafts/scheduled are never returned by public endpoints.

## Collections

### users
`id, email (unique, lower), passwordHash (argon2), role ("owner"|"editor"),
name, isActive, forcePasswordChange, failedLoginCount, lockedUntil?,
lastLoginAt?, createdAt, updatedAt`

### sessions  _(refresh-token store, rotation)_
`id, userId, refreshTokenHash, userAgent, ip, expiresAt, createdAt, revokedAt?`

### site_settings  _(singleton, id="settings")_
`brandName, tagline: LocalizedText, logoMediaId?, faviconMediaId?,
ownerPortraitMediaId?, aboutText: LocalizedText, contact: {phone?, whatsapp?,
email?, region?}, socials: [{platform, url}], supportedLanguages: [str],
defaultLanguage, currency, timezone, analytics: {gaId?, gscVerification?,
metaPixelId?}, cookieNotice: LocalizedText, emergencyNotice?: {enabled, text:
LocalizedText}, globalCta: {label: LocalizedText, href}, seoDefaults:
{titlePattern, description: LocalizedText, socialImageMediaId?, canonicalBaseUrl,
robots}, updatedAt, updatedBy`

### tours
Publishing envelope +
`slug (unique), name: LocalizedText, shortDescription: LocalizedText,
fullDescription: LocalizedText (rich HTML, sanitized), coverMediaId?,
galleryMediaIds: [id], promoVideoId?, destinationIds: [id], categories: [str],
durationHours?, durationDays?, startLocation?, endLocation?, suggestedStartTime?,
walkingDistanceKm?, drivingDistanceKm?, elevationGainM?, maxAltitudeM?,
difficulty ("easy"|"moderate"|"challenging"|"strenuous"), fitnessLevel?,
minAge?, groupSizeMin?, groupSizeMax?, tourType ("private"|"shared"|"custom"),
seasons: [str], weatherDependency?, accessibilityNotes: LocalizedText,
familyFriendly: bool, lowWalking: bool, winter: bool,
inclusions: [LocalizedText], exclusions: [LocalizedText],
whatToBring: [LocalizedText], itinerary: [{title: LocalizedText, body:
LocalizedText}], safetyNotes: LocalizedText, priceDisplay ("amount"|"contact"),
priceAmount?, currency, offerId?, featured: bool, displayOrder,
seo: SeoBlock`

### destinations
Publishing envelope +
`slug (unique), name: LocalizedText, intro: LocalizedText,
description: LocalizedText, coordinates: {lat, lng}, altitudeM?, bestSeasons:
[str], galleryMediaIds: [id], videoIds: [id], relatedTourIds: [id],
culturalNotes: LocalizedText, practicalAdvice: LocalizedText,
accessibilityInfo: LocalizedText, safetyNotice: LocalizedText,
relatedArticleIds: [id], displayOrder, seo: SeoBlock`

### banners
`id, name, placement ("announcement"|"hero"|"internal"|"promo"), title:
LocalizedText, subtitle: LocalizedText, desktopMediaId?, mobileMediaId?,
overlayIntensity (0..1), cta: {label: LocalizedText, href}?, pageTargets: [str]
(route globs, "*" = all), languageTargets: [str], priority, active: bool,
startAt?, endAt?, createdAt, updatedAt, createdBy, lastEditedBy`

### offers
Publishing envelope (status incl. "expired" computed) +
`title: LocalizedText, description: LocalizedText, code?, discountType
("percent"|"fixed"|"display"), discountValue?, terms: LocalizedText,
relatedTourIds: [id], bannerId?, cta: {label,href}?, featured: bool, priority,
languageTargets: [str], startAt?, endAt?`

### popups
`id, title: LocalizedText, body: LocalizedText, mediaId?, cta:{label,href}?,
startAt?, endAt?, pageTargets: [str], languageTargets: [str],
deviceTargets: ["desktop","mobile"], delaySeconds, scrollDepthPercent?,
exitIntent: bool, audience ("all"|"new"|"returning"),
frequency ("once_ever"|"once_session"|"once_day"|"every_visit"|"custom_days"),
frequencyDays?, dismissible: bool, priority, active: bool, createdAt, updatedAt`

### media
`id, kind ("image"|"video"|"external_video"), provider ("local"|"cloudinary"|
"s3"|"youtube"|"vimeo"), storageKey?, externalUrl?, originalFilename?, mimeType,
sizeBytes?, width?, height?, durationSeconds?, altText: LocalizedText,
caption: LocalizedText, credit?, location?, tags: [str], collection?,
posterMediaId?, variants: {thumb?, card?, hero?, original?} (each {url,w,h}),
usageRefs: [{collection, docId}], archived: bool, createdAt, createdBy`

### gallery_albums
`id, title: LocalizedText, slug, category?, coverMediaId?, mediaIds: [id],
displayOrder, published: bool, createdAt, updatedAt`

### videos
`id, title: LocalizedText, caption: LocalizedText, kind ("uploaded"|"youtube"|
"vimeo"), mediaId? | externalUrl?, posterMediaId?, featured: bool, displayOrder,
published: bool, createdAt, updatedAt`

### articles  _(travel guide / blog)_
Publishing envelope +
`slug (unique), title: LocalizedText, excerpt: LocalizedText, body: LocalizedText
(rich HTML), coverMediaId?, author, categories: [str], tags: [str],
relatedTourIds: [id], relatedDestinationIds: [id], readingMinutes?,
seo: SeoBlock`

### reviews
`id, reviewerName, country?, rating (1..5), text, date?, tourId?, source
("manual"|"google"|"tripadvisor"|"other"), sourceUrl?, permissionStatus
("granted"|"pending"|"unknown"), featured: bool, published: bool, isSample:
bool, createdAt`

### faqs
`id, question: LocalizedText, answer: LocalizedText, category, displayOrder,
published: bool`

### inquiries
`id, fullName, email, phone?, country?, preferredLanguage?, arrivalDate?,
departureDate?, flexibleDates: bool, groupSize?, children?, selectedTourId?,
interests: [str], activityLevel?, needTransport: bool, pickupLocation?,
accommodationStatus?, message, consent: bool, marketingOptIn: bool,
status ("new"|"reviewing"|"contacted"|"quoted"|"confirmed"|"completed"|
"closed"|"spam"), notes: [{authorId, text, at}], timeline: [{type, at, by,
summary}], ipHash?, createdAt, updatedAt`

### pages  _(modular page builder — homepage & others)_
`id, key (e.g. "home", unique), title, sections: [Section], updatedAt, updatedBy`
`Section = { id, type, hidden, startAt?, endAt?, order, data (type-specific) }`
Section types: `hero, richtext, split, tourGrid, destinationGrid, gallery,
video, testimonials, offers, faq, map, stats, cta, contactForm, announcement,
logoStrip, seasonalCards`.

### navigation  _(singleton id="navigation")_
`mainMenu: [{label: LocalizedText, href, children?}], footerGroups:
[{title: LocalizedText, links: [{label,href}]}], socialLinks: [{platform,url}],
legalLinks: [{label,href}], ctaButton: {label: LocalizedText, href}`

### redirects
`id, fromPath (unique), toPath, statusCode (301|302), createdAt, createdBy`

### audit_logs
`id, at, userId, userEmail, action ("login"|"login_failed"|"create"|"edit"|
"publish"|"unpublish"|"archive"|"delete"|"media_replace"|"user_change"|
"settings_change"), entity ("tour"|"offer"|...), entityId?, summary, ip?`

### content_meta  _(singleton id="content_meta")_
`version (int), updatedAt` — incremented on every publish/unpublish/settings
change. Served via ETag on public responses and `/api/public/content-version`.

## Shared sub-schema

`SeoBlock = { title?: LocalizedText, description?: LocalizedText,
ogImageMediaId?, noindex: bool, canonicalPath? }`

## Indexes

- `users.email` unique; `tours.slug`, `destinations.slug`, `articles.slug`,
  `gallery_albums.slug` unique; `redirects.fromPath` unique.
- Compound: `tours.{status, featured, displayOrder}`,
  `inquiries.{status, createdAt}`, `audit_logs.{at}` (desc),
  `banners.{active, priority}`, `offers.{status, priority}`.
