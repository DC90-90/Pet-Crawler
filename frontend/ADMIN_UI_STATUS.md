# Admin CMS UI — build status

Owner dashboard for "Svaneti with Georgie". All files below are the ONLY files
created/modified (nothing outside the owned set was touched).

## Verification
- Type-checked every owned file in isolation with a temporary scoped tsconfig
  (`strict`, `noUnusedLocals`, `noUnusedParameters`) → **0 errors in owned files**.
  The temp config was removed afterward.
- Not run: the whole-project `tsc`/build (public pages are in progress, per brief).
  One pre-existing environmental note surfaced only because of the scoped config:
  `src/lib/api.ts` uses `import.meta.env` which needs `vite/client` types — that
  file is NOT owned and resolves fine in the real app build.
- HeroUI component names/anatomies were verified against the installed
  `@heroui/react` d.ts (see "HeroUI notes" below), not just the docs.

## Files created

### Data layer
- `src/lib/admin.ts` — auth hooks (`useMe`, `useLogin`, `useLogout`,
  `useChangePassword`); generic `adminResource<T>()` factory →
  `toursApi/destinationsApi/bannersApi/offersApi/popupsApi/articlesApi/reviewsApi/faqsApi/redirectsApi/videosApi/galleryAlbumsApi`
  (each: useList/useOne/useCreate/useUpdate/useRemove/usePublish/useUnpublish);
  `useOverview`, `useInquiries`, `useUpdateInquiry`, `useAuditLogs`, users hooks,
  `useSettings`/`useUpdateSettings`, `useNavigationAdmin`/`useUpdateNavigation`,
  `usePage`/`useUpdatePage`, media hooks
  (`useMediaList/useUploadMedia/useRegisterExternalMedia/useUpdateMedia/useDeleteMedia`).
  Also: admin document types, `tx()` localizer, `errMessage()`, `mediaUrl()`, and a
  tiny toast store (`toast`, `subscribeToasts`, `dismissToast`). Every mutation
  invalidates its query key(s) and fires a success/error toast.

### Shell
- `src/app/AdminLayout.tsx` — `export Component`. Auth guard via `useMe()` (Spinner
  while loading; `<Navigate to="/admin/login">` on 401/403/failure). Fixed desktop
  sidebar (grouped Content/Media/Marketing/Inbox/Site/System) + top bar with user +
  role chip + logout + "View site". Mobile HeroUI `Drawer`. Users nav item is
  owner-only. Mounts `<Toaster/>`.

### Shared components (`src/components/admin/`)
- `AdminPageHeader.tsx`, `AdminTable.tsx` (generic column-based Table wrapper),
  `DataTableToolbar.tsx` (+ `Pager`), `StatusChip.tsx` (+ `PublishedChip`,
  `ActiveChip`), `ConfirmDialog.tsx`, `EditorModal.tsx`, `AdminEmptyState.tsx`
  (+ `LoadingState`, `ErrorState`), `LocalizedInput.tsx` (en/ka/ar tabs, RTL panel),
  `MediaPicker.tsx` (+ `MediaMultiPicker`, inline upload), `FormField.tsx`
  (`FormCard/FieldGrid/TextInput/TextAreaInput/NumberInput/SelectInput/SwitchInput/CheckboxInput/TagsInput`),
  `Toaster.tsx`, `constants.tsx` (option arrays).

### Pages (`src/pages/admin/`, each `export Component`)
LoginPage, OverviewPage, ToursAdminPage, TourEditPage, DestinationsAdminPage,
ArticlesPage, ReviewsPage, FaqsPage, GalleryAdminPage, VideosAdminPage, MediaPage,
BannersPage, OffersPage, PopupsPage, PagesPage, InquiriesPage, NavigationPage,
SeoPage, SettingsPage, UsersPage, AuditPage.

## Module status

### Fully functional (list/filter/paginate + create/edit + publish/delete + feedback)
- Tours (list) + Tour editor (full DATA_MODEL field coverage: localized name/short/
  full desc, slug, cover + gallery pickers, difficulty/type/seasons/flags, distances,
  itinerary repeater, inclusions/exclusions/whatToBring localized list editors,
  pricing, featured, SEO block, scheduling, publish/unpublish, preview link).
- Destinations, Articles, Reviews (manual-only + isSample + SampleFlag + warning),
  FAQs (grouped by category, ordered), Gallery albums, Videos, Banners, Offers,
  Popups — all list + modal editor + publish/active toggle + delete confirm.
- Media library (grid, search + kind filter, upload, register external video,
  alt/caption/credit/tags editing, delete with usageRefs guard) + reusable MediaPicker.
- Inquiries (table + filters + detail Drawer: all fields, status dropdown, notes
  add, timeline, WhatsApp/email actions, Export CSV link).
- Pages builder for "home" (dnd-kit reorder, add from SectionType menu, duplicate,
  hide/show, delete, per-section data editor + scheduling, Save, Preview link).
- Navigation (main menu / footer groups / social / legal / CTA repeaters).
- SEO (defaults + redirect manager) . Settings (brand/contact/socials/languages/
  cookie/emergency/global CTA + owner-only analytics, "needs owner verification"
  badges). Users (owner-guarded CRUD + activate/deactivate). Audit log (paginated).
- Overview dashboard (stat cards from `useOverview`, quick-create, recent activity).

### Simplified / assumptions to confirm at integration
- **Overview** (`useOverview`) response shape is assumed
  (`{tours:{published,draft}, offers:{active,scheduled}, popups:{active},
  inquiries:{new}, media:{recent}, needsVerification, recentActivity[]}`) and read
  defensively with `?? 0`. Adjust keys to the real payload if different.
- **Pages builder** section-data editor is a generic type-aware editor
  (string→text, boolean→switch, number→number, object/array→JSON textarea) plus an
  "add field" affordance — NOT bespoke per-section-type forms. It never exposes raw
  HTML. Per-type curated forms can be layered later.
- **Rich text** (tour/article body) uses a plain multiline textarea with a
  "sanitized server-side" hint — no WYSIWYG was in scope.
- **Login**: uses react-hook-form `register` spread onto HeroUI `<Input>` inside an
  uncontrolled `<TextField>` (RAC forwards the ref). Works, but worth a click-test.
- **Inquiry notes** send the full `notes` array with `{authorId: me.id, text, at}`;
  if the backend prefers a single `note` append field, adjust `addNote`.
- List filter params passed to `useList` (`status`, `placement`, `kind`, `q`, `page`,
  `pageSize`) assume those query-param names on the backend.
- CSV export is a plain `<a download href="${apiBase}/api/admin/inquiries/export.csv">`
  relying on the auth cookie (same-origin). If the endpoint needs the CSRF header it
  will need a fetch+blob approach instead.

## HeroUI notes / API points I want you to double-check at integration build
- **Textarea is exported as `TextArea`** (capital A) in this version — used via the
  shared `TextAreaInput`/`LocalizedInput` wrappers.
- **Modal**: controlled `isOpen`/`onOpenChange` sit on the `Modal` root
  (it's a RAC `DialogTrigger`); `isDismissable`/`variant` sit on `Modal.Backdrop`.
  I render controlled modals WITHOUT a trigger child (per the brief's verified
  anatomy) — it type-checks; please confirm it opens/closes at runtime. Same shape
  for `Drawer` (`Drawer.Content placement=...`).
- **Drawer `placement`** only accepts physical `top|bottom|left|right` (no logical
  `start|end`), so the mobile sidebar uses `left` and the inquiry drawer uses
  `right`. In RTL these won't mirror automatically — flip if needed.
- **Button** has no `isLoading` in the installed types, so all pending states use
  `isDisabled={mutation.isPending}` + a label swap ("Saving…"). No `onClick`, no
  `as={Link}` on Button anywhere (navigation uses `onPress`+`useNavigate`).
- **Select**: `selectedKey` + `onSelectionChange` (RAC Select) — wrapped by
  `SelectInput`. Chips use `variant` in {primary,secondary,soft,tertiary} and
  `color` in {accent,danger,default,success,warning}.
