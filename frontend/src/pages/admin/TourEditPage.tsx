import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Button, Separator } from "@heroui/react";
import {
  toursApi,
  tx,
  errMessage,
  type AdminTour,
  type SeoBlock,
} from "@/lib/admin";
import type { LocalizedText } from "@/lib/types";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { LoadingState, ErrorState } from "@/components/admin/AdminEmptyState";
import { StatusChip } from "@/components/admin/StatusChip";
import { LocalizedInput } from "@/components/admin/LocalizedInput";
import { MediaPicker, MediaMultiPicker } from "@/components/admin/MediaPicker";
import {
  FormCard,
  FieldGrid,
  TextInput,
  NumberInput,
  SelectInput,
  SwitchInput,
  TagsInput,
} from "@/components/admin/FormField";
import {
  DIFFICULTY_OPTIONS,
  TOUR_TYPE_OPTIONS,
  PRICE_DISPLAY_OPTIONS,
  SEASON_OPTIONS,
} from "@/components/admin/constants";

/* ---------- localized list editor (inclusions / exclusions / bring) ---------- */
function LocalizedListEditor({
  label,
  items,
  onChange,
}: {
  label: string;
  items: LocalizedText[];
  onChange: (v: LocalizedText[]) => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-foreground">{label}</span>
        <Button
          variant="outline"
          size="sm"
          onPress={() => onChange([...items, { en: "" }])}
        >
          Add item
        </Button>
      </div>
      {items.length === 0 && <p className="text-xs text-muted">No items yet.</p>}
      {items.map((item, i) => (
        <div key={i} className="flex items-start gap-2 rounded-lg border border-border p-2">
          <div className="flex-1">
            <LocalizedInput
              label={`Item ${i + 1}`}
              value={item}
              onChange={(v) => onChange(items.map((it, idx) => (idx === i ? v : it)))}
            />
          </div>
          <Button
            variant="tertiary"
            size="sm"
            aria-label="Remove item"
            onPress={() => onChange(items.filter((_, idx) => idx !== i))}
          >
            ✕
          </Button>
        </div>
      ))}
    </div>
  );
}

/* ---------- itinerary editor ---------- */
function ItineraryEditor({
  items,
  onChange,
}: {
  items: { title: LocalizedText; body: LocalizedText }[];
  onChange: (v: { title: LocalizedText; body: LocalizedText }[]) => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-foreground">Itinerary</span>
        <Button
          variant="outline"
          size="sm"
          onPress={() => onChange([...items, { title: { en: "" }, body: { en: "" } }])}
        >
          Add step
        </Button>
      </div>
      {items.map((step, i) => (
        <div key={i} className="flex flex-col gap-2 rounded-lg border border-border p-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted">
              Step {i + 1}
            </span>
            <Button
              variant="tertiary"
              size="sm"
              aria-label="Remove step"
              onPress={() => onChange(items.filter((_, idx) => idx !== i))}
            >
              ✕
            </Button>
          </div>
          <LocalizedInput
            label="Title"
            value={step.title}
            onChange={(v) =>
              onChange(items.map((s, idx) => (idx === i ? { ...s, title: v } : s)))
            }
          />
          <LocalizedInput
            label="Details"
            multiline
            value={step.body}
            onChange={(v) =>
              onChange(items.map((s, idx) => (idx === i ? { ...s, body: v } : s)))
            }
          />
        </div>
      ))}
    </div>
  );
}

/* ---------- SEO block editor ---------- */
function SeoEditor({
  value,
  onChange,
}: {
  value: SeoBlock;
  onChange: (v: SeoBlock) => void;
}) {
  return (
    <div className="flex flex-col gap-4">
      <LocalizedInput
        label="SEO title"
        value={value.title}
        onChange={(v) => onChange({ ...value, title: v })}
      />
      <LocalizedInput
        label="SEO description"
        multiline
        rows={3}
        value={value.description}
        onChange={(v) => onChange({ ...value, description: v })}
      />
      <MediaPicker
        label="Social share image"
        value={value.ogImageMediaId}
        onChange={(id) => onChange({ ...value, ogImageMediaId: id })}
      />
      <TextInput
        label="Canonical path"
        value={value.canonicalPath ?? ""}
        onChange={(v) => onChange({ ...value, canonicalPath: v || undefined })}
        placeholder="/tours/ushguli-day-hike"
      />
      <SwitchInput
        label="Hide from search engines (noindex)"
        value={!!value.noindex}
        onChange={(v) => onChange({ ...value, noindex: v })}
      />
    </div>
  );
}

const EMPTY_TOUR: Partial<AdminTour> = {
  status: "draft",
  priceDisplay: "contact",
  name: { en: "" },
  shortDescription: { en: "" },
  familyFriendly: false,
  lowWalking: false,
  winter: false,
  featured: false,
};

export function Component() {
  const { id = "new" } = useParams();
  const isNew = id === "new";
  const navigate = useNavigate();

  const { data, isLoading, isError, error } = toursApi.useOne(id);
  const create = toursApi.useCreate();
  const update = toursApi.useUpdate();
  const publish = toursApi.usePublish();
  const unpublish = toursApi.useUnpublish();

  const [form, setForm] = useState<Partial<AdminTour>>(EMPTY_TOUR);

  useEffect(() => {
    if (data) setForm(data);
  }, [data]);

  const set = <K extends keyof AdminTour>(key: K, value: AdminTour[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  if (!isNew && isLoading) return <LoadingState />;
  if (!isNew && isError) return <ErrorState message={errMessage(error)} />;

  const save = () => {
    if (isNew) {
      create.mutate(form, {
        onSuccess: (created) => navigate(`/admin/tours/${created.id}`, { replace: true }),
      });
    } else {
      update.mutate({ id, data: form });
    }
  };

  const saving = create.isPending || update.isPending;

  return (
    <div>
      <AdminPageHeader
        title={isNew ? "New tour" : tx(form.name) || "Edit tour"}
        breadcrumb={
          <button onClick={() => navigate("/admin/tours")} className="hover:text-copper">
            ← Tours
          </button>
        }
        actions={
          <div className="flex items-center gap-2">
            {!isNew && <StatusChip status={form.status} />}
            {!isNew && form.slug && (
              <a
                href={`/en/tours/${form.slug}`}
                target="_blank"
                rel="noreferrer"
                className="text-sm text-muted hover:text-foreground"
              >
                Preview ↗
              </a>
            )}
            {!isNew &&
              (form.status === "published" ? (
                <Button
                  variant="outline"
                  size="sm"
                  onPress={() => unpublish.mutate(id)}
                  isDisabled={unpublish.isPending}
                >
                  Unpublish
                </Button>
              ) : (
                <Button
                  variant="secondary"
                  size="sm"
                  onPress={() => publish.mutate(id)}
                  isDisabled={publish.isPending}
                >
                  Publish
                </Button>
              ))}
            <Button variant="primary" size="sm" onPress={save} isDisabled={saving}>
              {saving ? "Saving…" : "Save"}
            </Button>
          </div>
        }
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="flex flex-col gap-6 lg:col-span-2">
          <FormCard title="Basics">
            <TextInput
              label="Slug"
              value={form.slug ?? ""}
              onChange={(v) => set("slug", v)}
              placeholder="ushguli-day-hike"
              isRequired
              hint="Lowercase, hyphenated. Used in the public URL."
            />
            <LocalizedInput
              label="Name"
              value={form.name}
              onChange={(v) => set("name", v)}
            />
            <LocalizedInput
              label="Short description"
              multiline
              rows={2}
              value={form.shortDescription}
              onChange={(v) => set("shortDescription", v)}
            />
            <LocalizedInput
              label="Full description"
              multiline
              rows={6}
              value={form.fullDescription}
              onChange={(v) => set("fullDescription", v)}
              hint="Rich text is sanitized server-side."
            />
          </FormCard>

          <FormCard title="Media">
            <MediaPicker
              label="Cover image"
              value={form.coverMediaId}
              onChange={(id2) => set("coverMediaId", id2)}
            />
            <MediaMultiPicker
              label="Gallery"
              value={form.galleryMediaIds ?? []}
              onChange={(ids) => set("galleryMediaIds", ids)}
            />
          </FormCard>

          <FormCard title="Details">
            <FieldGrid>
              <SelectInput
                label="Difficulty"
                value={form.difficulty}
                onChange={(v) => set("difficulty", v as AdminTour["difficulty"])}
                options={DIFFICULTY_OPTIONS}
              />
              <SelectInput
                label="Tour type"
                value={form.tourType}
                onChange={(v) => set("tourType", v as AdminTour["tourType"])}
                options={TOUR_TYPE_OPTIONS}
              />
              <NumberInput
                label="Duration (days)"
                value={form.durationDays}
                onChange={(v) => set("durationDays", v)}
                min={0}
              />
              <NumberInput
                label="Duration (hours)"
                value={form.durationHours}
                onChange={(v) => set("durationHours", v)}
                min={0}
              />
              <NumberInput
                label="Walking distance (km)"
                value={form.walkingDistanceKm}
                onChange={(v) => set("walkingDistanceKm", v)}
                min={0}
              />
              <NumberInput
                label="Max altitude (m)"
                value={form.maxAltitudeM}
                onChange={(v) => set("maxAltitudeM", v)}
                min={0}
              />
              <NumberInput
                label="Min age"
                value={form.minAge}
                onChange={(v) => set("minAge", v)}
                min={0}
              />
              <NumberInput
                label="Max group size"
                value={form.groupSizeMax}
                onChange={(v) => set("groupSizeMax", v)}
                min={0}
              />
            </FieldGrid>
            <TagsInput
              label="Seasons"
              value={form.seasons ?? []}
              onChange={(v) => set("seasons", v)}
              hint={`Suggested: ${SEASON_OPTIONS.map((s) => s.value).join(", ")}`}
            />
            <TagsInput
              label="Categories"
              value={form.categories ?? []}
              onChange={(v) => set("categories", v)}
            />
            <div className="flex flex-wrap gap-4">
              <SwitchInput
                label="Family friendly"
                value={!!form.familyFriendly}
                onChange={(v) => set("familyFriendly", v)}
              />
              <SwitchInput
                label="Low walking"
                value={!!form.lowWalking}
                onChange={(v) => set("lowWalking", v)}
              />
              <SwitchInput
                label="Winter tour"
                value={!!form.winter}
                onChange={(v) => set("winter", v)}
              />
            </div>
          </FormCard>

          <FormCard title="Itinerary & lists">
            <ItineraryEditor
              items={form.itinerary ?? []}
              onChange={(v) => set("itinerary", v)}
            />
            <Separator />
            <LocalizedListEditor
              label="Inclusions"
              items={form.inclusions ?? []}
              onChange={(v) => set("inclusions", v)}
            />
            <Separator />
            <LocalizedListEditor
              label="Exclusions"
              items={form.exclusions ?? []}
              onChange={(v) => set("exclusions", v)}
            />
            <Separator />
            <LocalizedListEditor
              label="What to bring"
              items={form.whatToBring ?? []}
              onChange={(v) => set("whatToBring", v)}
            />
          </FormCard>

          <FormCard title="SEO">
            <SeoEditor
              value={form.seo ?? { noindex: false }}
              onChange={(v) => set("seo", v)}
            />
          </FormCard>
        </div>

        {/* Sidebar */}
        <div className="flex flex-col gap-6">
          <FormCard title="Pricing">
            <SelectInput
              label="Price display"
              value={form.priceDisplay}
              onChange={(v) => set("priceDisplay", v as AdminTour["priceDisplay"])}
              options={PRICE_DISPLAY_OPTIONS}
            />
            {form.priceDisplay === "amount" && (
              <FieldGrid>
                <NumberInput
                  label="Amount"
                  value={form.priceAmount}
                  onChange={(v) => set("priceAmount", v)}
                  min={0}
                />
                <TextInput
                  label="Currency"
                  value={form.currency ?? ""}
                  onChange={(v) => set("currency", v)}
                  placeholder="GEL"
                />
              </FieldGrid>
            )}
            <SwitchInput
              label="Featured on home"
              value={!!form.featured}
              onChange={(v) => set("featured", v)}
            />
            <NumberInput
              label="Display order"
              value={form.displayOrder}
              onChange={(v) => set("displayOrder", v)}
            />
          </FormCard>

          <FormCard title="Scheduling">
            <TextInput
              label="Publish at"
              type="datetime-local"
              value={form.publishAt ?? ""}
              onChange={(v) => set("publishAt", v || undefined)}
            />
            <TextInput
              label="Unpublish at"
              type="datetime-local"
              value={form.unpublishAt ?? ""}
              onChange={(v) => set("unpublishAt", v || undefined)}
            />
          </FormCard>
        </div>
      </div>
    </div>
  );
}
