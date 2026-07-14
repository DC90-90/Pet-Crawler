import { useEffect, useState } from "react";
import {
  DndContext,
  closestCenter,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Button, Chip, Dropdown, Alert } from "@heroui/react";
import { usePage, useUpdatePage, errMessage } from "@/lib/admin";
import type { PageSection, SectionType } from "@/lib/types";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { LoadingState, ErrorState } from "@/components/admin/AdminEmptyState";
import {
  TextInput,
  NumberInput,
  SwitchInput,
  TextAreaInput,
} from "@/components/admin/FormField";

const SECTION_TYPES: SectionType[] = [
  "hero",
  "richtext",
  "split",
  "tourGrid",
  "destinationGrid",
  "gallery",
  "video",
  "testimonials",
  "offers",
  "faq",
  "map",
  "stats",
  "cta",
  "contactForm",
  "announcement",
  "logoStrip",
  "seasonalCards",
];

type SectionData = Record<string, unknown>;
/** DATA_MODEL sections carry optional scheduling not present in the lean UI type. */
type BuilderSection = PageSection & { startAt?: string; endAt?: string };

function genId() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `s_${Date.now()}_${Math.random().toString(36).slice(2)}`;
}

/** Generic, type-agnostic editor for a section's data object (no raw HTML). */
function SectionDataEditor({
  data,
  onChange,
}: {
  data: SectionData;
  onChange: (d: SectionData) => void;
}) {
  const entries = Object.entries(data);
  const set = (key: string, value: unknown) => onChange({ ...data, [key]: value });

  if (entries.length === 0) {
    return (
      <p className="text-xs text-muted">
        This section has no configurable fields yet. Add one below.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {entries.map(([key, value]) => {
        if (typeof value === "string") {
          return (
            <TextInput
              key={key}
              label={key}
              value={value}
              onChange={(v) => set(key, v)}
            />
          );
        }
        if (typeof value === "boolean") {
          return (
            <SwitchInput key={key} label={key} value={value} onChange={(v) => set(key, v)} />
          );
        }
        if (typeof value === "number") {
          return (
            <NumberInput
              key={key}
              label={key}
              value={value}
              onChange={(v) => set(key, v ?? 0)}
            />
          );
        }
        // objects / arrays → JSON editor
        return (
          <TextAreaInput
            key={key}
            label={`${key} (JSON)`}
            rows={3}
            value={JSON.stringify(value, null, 2)}
            onChange={(raw) => {
              try {
                set(key, JSON.parse(raw));
              } catch {
                /* keep last valid value until JSON parses */
              }
            }}
          />
        );
      })}
    </div>
  );
}

function AddFieldRow({ onAdd }: { onAdd: (key: string) => void }) {
  const [key, setKey] = useState("");
  return (
    <div className="flex items-end gap-2">
      <div className="flex-1">
        <TextInput label="Add text field" value={key} onChange={setKey} placeholder="e.g. heading" />
      </div>
      <Button
        variant="outline"
        size="sm"
        isDisabled={!key.trim()}
        onPress={() => {
          onAdd(key.trim());
          setKey("");
        }}
      >
        Add
      </Button>
    </div>
  );
}

function SortableSection({
  section,
  onChange,
  onDuplicate,
  onDelete,
}: {
  section: BuilderSection;
  onChange: (s: BuilderSection) => void;
  onDuplicate: () => void;
  onDelete: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: section.id });
  const [open, setOpen] = useState(false);

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.6 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className="rounded-xl border border-border bg-surface/50"
    >
      <div className="flex items-center gap-2 p-3">
        <button
          type="button"
          className="cursor-grab px-1 text-muted"
          aria-label="Drag to reorder"
          {...attributes}
          {...listeners}
        >
          ⠿
        </button>
        <Chip size="sm" variant="soft" color="accent">
          {section.type}
        </Chip>
        {section.hidden && (
          <Chip size="sm" variant="soft" color="default">
            Hidden
          </Chip>
        )}
        <div className="ms-auto flex items-center gap-1">
          <Button variant="tertiary" size="sm" onPress={() => setOpen((o) => !o)}>
            {open ? "Close" : "Edit"}
          </Button>
          <Dropdown>
              <Button variant="outline" size="sm" isIconOnly aria-label="Section actions">
                ⋯
              </Button>
            <Dropdown.Popover>
              <Dropdown.Menu
                onAction={(key) => {
                  const k = String(key);
                  if (k === "hide") onChange({ ...section, hidden: !section.hidden });
                  else if (k === "duplicate") onDuplicate();
                  else if (k === "delete") onDelete();
                }}
              >
                <Dropdown.Item id="hide">
                  {section.hidden ? "Show" : "Hide"}
                </Dropdown.Item>
                <Dropdown.Item id="duplicate">Duplicate</Dropdown.Item>
                <Dropdown.Item id="delete">Delete</Dropdown.Item>
              </Dropdown.Menu>
            </Dropdown.Popover>
          </Dropdown>
        </div>
      </div>
      {open && (
        <div className="flex flex-col gap-3 border-t border-border p-3">
          <SectionDataEditor
            data={section.data as SectionData}
            onChange={(d) => onChange({ ...section, data: d })}
          />
          <AddFieldRow
            onAdd={(key) =>
              onChange({ ...section, data: { ...section.data, [key]: "" } })
            }
          />
          <div className="grid grid-cols-2 gap-2">
            <TextInput
              label="Schedule start"
              type="datetime-local"
              value={section.startAt ?? ""}
              onChange={(v) => onChange({ ...section, startAt: v || undefined })}
            />
            <TextInput
              label="Schedule end"
              type="datetime-local"
              value={section.endAt ?? ""}
              onChange={(v) => onChange({ ...section, endAt: v || undefined })}
            />
          </div>
        </div>
      )}
    </div>
  );
}

export function Component() {
  const { data, isLoading, isError, error } = usePage("home");
  const updatePage = useUpdatePage();
  const [sections, setSections] = useState<BuilderSection[]>([]);

  useEffect(() => {
    if (data?.sections) setSections(data.sections);
  }, [data]);

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  if (isLoading) return <LoadingState />;
  if (isError) return <ErrorState message={errMessage(error)} />;

  const onDragEnd = (e: DragEndEvent) => {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    setSections((prev) => {
      const oldIndex = prev.findIndex((s) => s.id === active.id);
      const newIndex = prev.findIndex((s) => s.id === over.id);
      return arrayMove(prev, oldIndex, newIndex).map((s, i) => ({ ...s, order: i }));
    });
  };

  const addSection = (type: SectionType) =>
    setSections((prev) => [
      ...prev,
      { id: genId(), type, hidden: false, order: prev.length, data: {} },
    ]);

  const updateSection = (s: BuilderSection) =>
    setSections((prev) => prev.map((x) => (x.id === s.id ? s : x)));

  const duplicateSection = (id: string) =>
    setSections((prev) => {
      const src = prev.find((s) => s.id === id);
      if (!src) return prev;
      const copy: BuilderSection = { ...src, id: genId() };
      const idx = prev.findIndex((s) => s.id === id);
      const next = [...prev.slice(0, idx + 1), copy, ...prev.slice(idx + 1)];
      return next.map((s, i) => ({ ...s, order: i }));
    });

  const deleteSection = (id: string) =>
    setSections((prev) =>
      prev.filter((s) => s.id !== id).map((s, i) => ({ ...s, order: i })),
    );

  const save = () =>
    updatePage.mutate({
      key: "home",
      data: { key: "home", title: data?.title ?? "Home", sections },
    });

  return (
    <div>
      <AdminPageHeader
        title="Home page builder"
        description="Arrange, schedule and edit the homepage sections."
        actions={
          <div className="flex items-center gap-2">
            <a href="/" target="_blank" rel="noreferrer" className="text-sm text-muted hover:text-foreground">
              Preview ↗
            </a>
            <Dropdown>
                <Button variant="outline" size="sm">
                  Add section
                </Button>
              <Dropdown.Popover>
                <Dropdown.Menu onAction={(key) => addSection(String(key) as SectionType)}>
                  {SECTION_TYPES.map((t) => (
                    <Dropdown.Item key={t} id={t}>
                      {t}
                    </Dropdown.Item>
                  ))}
                </Dropdown.Menu>
              </Dropdown.Popover>
            </Dropdown>
            <Button
              variant="primary"
              size="sm"
              onPress={save}
              isDisabled={updatePage.isPending}
            >
              {updatePage.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        }
      />

      {sections.length === 0 ? (
        <Alert color="default">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>No sections yet</Alert.Title>
            <Alert.Description>
              Use “Add section” to start composing the homepage.
            </Alert.Description>
          </Alert.Content>
        </Alert>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
          <SortableContext
            items={sections.map((s) => s.id)}
            strategy={verticalListSortingStrategy}
          >
            <div className="flex flex-col gap-3">
              {sections.map((s) => (
                <SortableSection
                  key={s.id}
                  section={s}
                  onChange={updateSection}
                  onDuplicate={() => duplicateSection(s.id)}
                  onDelete={() => deleteSection(s.id)}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}
    </div>
  );
}
