import { useState } from "react";
import { Button, Dropdown } from "@heroui/react";
import { bannersApi, tx, errMessage, type AdminBanner } from "@/lib/admin";
import type { Cta } from "@/lib/types";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { DataTableToolbar, Pager } from "@/components/admin/DataTableToolbar";
import { ActiveChip } from "@/components/admin/StatusChip";
import { ConfirmDialog } from "@/components/admin/ConfirmDialog";
import { EditorModal } from "@/components/admin/EditorModal";
import { LocalizedInput } from "@/components/admin/LocalizedInput";
import { MediaPicker } from "@/components/admin/MediaPicker";
import {
  LoadingState,
  ErrorState,
  AdminEmptyState,
} from "@/components/admin/AdminEmptyState";
import {
  FormCard,
  TextInput,
  NumberInput,
  SelectInput,
  SwitchInput,
  TagsInput,
} from "@/components/admin/FormField";
import { BANNER_PLACEMENT_OPTIONS } from "@/components/admin/constants";

const PAGE_SIZE = 20;
const PLACEMENT_FILTER_OPTIONS = [
  { value: "", label: "All placements" },
  ...BANNER_PLACEMENT_OPTIONS,
];
const EMPTY: Partial<AdminBanner> = {
  name: "",
  placement: "announcement",
  title: { en: "" },
  active: true,
};

export function Component() {
  const [q, setQ] = useState("");
  const [placement, setPlacement] = useState("");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Partial<AdminBanner> | null>(null);
  const [toDelete, setToDelete] = useState<AdminBanner | null>(null);

  const { data, isLoading, isError, error } = bannersApi.useList({
    q,
    placement: placement || undefined,
    page,
    pageSize: PAGE_SIZE,
  });
  const create = bannersApi.useCreate();
  const update = bannersApi.useUpdate();
  const remove = bannersApi.useRemove();

  const items = data?.items ?? [];
  const setField = <K extends keyof AdminBanner>(k: K, v: AdminBanner[K]) =>
    setEditing((e) => (e ? { ...e, [k]: v } : e));

  const setCta = (patch: Partial<Cta>) =>
    setEditing((e) =>
      e
        ? {
            ...e,
            cta: {
              label: e.cta?.label ?? { en: "" },
              href: e.cta?.href ?? "",
              ...patch,
            },
          }
        : e,
    );

  const save = () => {
    if (!editing) return;
    if (editing.id)
      update.mutate(
        { id: editing.id, data: editing },
        { onSuccess: () => setEditing(null) },
      );
    else create.mutate(editing, { onSuccess: () => setEditing(null) });
  };

  const columns: Column<AdminBanner>[] = [
    {
      key: "name",
      header: "Name",
      render: (b) => (
        <button
          type="button"
          onClick={() => setEditing(b)}
          className="text-start font-medium text-foreground hover:text-copper"
        >
          {b.name || tx(b.title) || "Untitled"}
        </button>
      ),
    },
    {
      key: "placement",
      header: "Placement",
      render: (b) => (
        <span className="text-sm capitalize text-muted">{b.placement}</span>
      ),
    },
    { key: "active", header: "Active", render: (b) => <ActiveChip active={b.active} /> },
    {
      key: "priority",
      header: "Priority",
      render: (b) => (
        <span className="text-sm text-muted">{b.priority ?? "—"}</span>
      ),
    },
    {
      key: "actions",
      header: "",
      align: "end",
      render: (b) => (
        <Dropdown>
            <Button variant="outline" size="sm" isIconOnly aria-label="Actions">
              ⋯
            </Button>
          <Dropdown.Popover>
            <Dropdown.Menu
              onAction={(key) => {
                const k = String(key);
                if (k === "edit") setEditing(b);
                else if (k === "toggle")
                  update.mutate({ id: b.id, data: { active: !b.active } });
                else if (k === "delete") setToDelete(b);
              }}
            >
              <Dropdown.Item id="edit">Edit</Dropdown.Item>
              <Dropdown.Item id="toggle">
                {b.active ? "Deactivate" : "Activate"}
              </Dropdown.Item>
              <Dropdown.Item id="delete">Delete</Dropdown.Item>
            </Dropdown.Menu>
          </Dropdown.Popover>
        </Dropdown>
      ),
    },
  ];

  return (
    <div>
      <AdminPageHeader
        title="Banners"
        description="Promotional and announcement banners across the site."
        actions={
          <Button variant="primary" size="sm" onPress={() => setEditing({ ...EMPTY })}>
            New banner
          </Button>
        }
      />

      <DataTableToolbar
        search={q}
        onSearch={(v) => {
          setQ(v);
          setPage(1);
        }}
        searchPlaceholder="Search banners…"
        filters={[
          {
            label: "Placement",
            value: placement,
            onChange: (v) => {
              setPlacement(v);
              setPage(1);
            },
            options: PLACEMENT_FILTER_OPTIONS,
          },
        ]}
      />

      {isLoading ? (
        <LoadingState />
      ) : isError ? (
        <ErrorState message={errMessage(error)} />
      ) : items.length === 0 ? (
        <AdminEmptyState
          title="No banners yet"
          action={
            <Button variant="primary" onPress={() => setEditing({ ...EMPTY })}>
              New banner
            </Button>
          }
        />
      ) : (
        <>
          <AdminTable columns={columns} rows={items} ariaLabel="Banners" />
          <Pager
            page={data?.page ?? page}
            pageSize={data?.pageSize ?? PAGE_SIZE}
            total={data?.total ?? items.length}
            onPage={setPage}
          />
        </>
      )}

      <EditorModal
        isOpen={!!editing}
        onOpenChange={(open) => !open && setEditing(null)}
        title={editing?.id ? "Edit banner" : "New banner"}
        onSave={save}
        isSaving={create.isPending || update.isPending}
      >
        {editing && (
          <>
            <TextInput
              label="Name"
              value={editing.name ?? ""}
              onChange={(v) => setField("name", v)}
              isRequired
              hint="Internal reference name."
            />
            <SelectInput
              label="Placement"
              value={editing.placement}
              onChange={(v) => setField("placement", v as AdminBanner["placement"])}
              options={BANNER_PLACEMENT_OPTIONS}
            />
            <LocalizedInput
              label="Title"
              value={editing.title}
              onChange={(v) => setField("title", v)}
            />
            <LocalizedInput
              label="Subtitle"
              multiline
              rows={2}
              value={editing.subtitle}
              onChange={(v) => setField("subtitle", v)}
            />
            <MediaPicker
              label="Desktop media"
              value={editing.desktopMediaId}
              onChange={(id) => setField("desktopMediaId", id)}
            />
            <MediaPicker
              label="Mobile media"
              value={editing.mobileMediaId}
              onChange={(id) => setField("mobileMediaId", id)}
            />
            <NumberInput
              label="Overlay intensity"
              value={editing.overlayIntensity}
              onChange={(v) => setField("overlayIntensity", v)}
              min={0}
              max={1}
              step={0.1}
              hint="0 = no overlay, 1 = fully opaque."
            />
            <FormCard title="Call to action" description="Optional button on the banner.">
              <LocalizedInput
                label="CTA label"
                value={editing.cta?.label}
                onChange={(v) => setCta({ label: v })}
              />
              <TextInput
                label="CTA link"
                value={editing.cta?.href ?? ""}
                onChange={(v) => setCta({ href: v })}
                placeholder="/tours or https://…"
              />
            </FormCard>
            <TagsInput
              label="Page targets"
              value={editing.pageTargets ?? []}
              onChange={(v) => setField("pageTargets", v)}
              hint='Route globs, "*" = all pages.'
            />
            <TagsInput
              label="Language targets"
              value={editing.languageTargets ?? []}
              onChange={(v) => setField("languageTargets", v)}
            />
            <NumberInput
              label="Priority"
              value={editing.priority}
              onChange={(v) => setField("priority", v)}
            />
            <SwitchInput
              label="Active"
              value={!!editing.active}
              onChange={(v) => setField("active", v)}
            />
            <TextInput
              label="Start at"
              type="datetime-local"
              value={editing.startAt ?? ""}
              onChange={(v) => setField("startAt", v || undefined)}
            />
            <TextInput
              label="End at"
              type="datetime-local"
              value={editing.endAt ?? ""}
              onChange={(v) => setField("endAt", v || undefined)}
            />
          </>
        )}
      </EditorModal>

      <ConfirmDialog
        isOpen={!!toDelete}
        onOpenChange={(open) => !open && setToDelete(null)}
        title="Delete banner?"
        body={`"${toDelete?.name ?? ""}" will be permanently removed.`}
        destructive
        confirmLabel="Delete"
        isPending={remove.isPending}
        onConfirm={() =>
          toDelete && remove.mutate(toDelete.id, { onSuccess: () => setToDelete(null) })
        }
      />
    </div>
  );
}
