import { useState } from "react";
import { Button, Dropdown } from "@heroui/react";
import { popupsApi, tx, errMessage, type AdminPopup } from "@/lib/admin";
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
  CheckboxInput,
  TagsInput,
} from "@/components/admin/FormField";
import {
  POPUP_FREQUENCY_OPTIONS,
  AUDIENCE_OPTIONS,
} from "@/components/admin/constants";

const PAGE_SIZE = 20;
const EMPTY: Partial<AdminPopup> = {
  title: { en: "" },
  body: { en: "" },
  frequency: "once_session",
  active: true,
};

const FREQUENCY_LABEL: Record<string, string> = Object.fromEntries(
  POPUP_FREQUENCY_OPTIONS.map((o) => [o.value, o.label]),
);
const AUDIENCE_LABEL: Record<string, string> = Object.fromEntries(
  AUDIENCE_OPTIONS.map((o) => [o.value, o.label]),
);

type Device = "desktop" | "mobile";

export function Component() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Partial<AdminPopup> | null>(null);
  const [toDelete, setToDelete] = useState<AdminPopup | null>(null);

  const { data, isLoading, isError, error } = popupsApi.useList({
    q,
    page,
    pageSize: PAGE_SIZE,
  });
  const create = popupsApi.useCreate();
  const update = popupsApi.useUpdate();
  const remove = popupsApi.useRemove();

  const items = data?.items ?? [];
  const setField = <K extends keyof AdminPopup>(k: K, v: AdminPopup[K]) =>
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

  const toggleDevice = (device: Device, on: boolean) =>
    setEditing((e) => {
      if (!e) return e;
      const current = e.deviceTargets ?? [];
      const next = on
        ? current.includes(device)
          ? current
          : [...current, device]
        : current.filter((d) => d !== device);
      return { ...e, deviceTargets: next };
    });

  const save = () => {
    if (!editing) return;
    if (editing.id)
      update.mutate(
        { id: editing.id, data: editing },
        { onSuccess: () => setEditing(null) },
      );
    else create.mutate(editing, { onSuccess: () => setEditing(null) });
  };

  const columns: Column<AdminPopup>[] = [
    {
      key: "title",
      header: "Title",
      render: (p) => (
        <button
          type="button"
          onClick={() => setEditing(p)}
          className="text-start font-medium text-foreground hover:text-copper"
        >
          {tx(p.title) || "Untitled"}
        </button>
      ),
    },
    {
      key: "frequency",
      header: "Frequency",
      render: (p) => (
        <span className="text-sm text-muted">
          {FREQUENCY_LABEL[p.frequency] ?? p.frequency}
        </span>
      ),
    },
    {
      key: "audience",
      header: "Audience",
      render: (p) => (
        <span className="text-sm text-muted">
          {p.audience ? AUDIENCE_LABEL[p.audience] ?? p.audience : "—"}
        </span>
      ),
    },
    { key: "active", header: "Active", render: (p) => <ActiveChip active={p.active} /> },
    {
      key: "actions",
      header: "",
      align: "end",
      render: (p) => (
        <Dropdown>
            <Button variant="outline" size="sm" isIconOnly aria-label="Actions">
              ⋯
            </Button>
          <Dropdown.Popover>
            <Dropdown.Menu
              onAction={(key) => {
                const k = String(key);
                if (k === "edit") setEditing(p);
                else if (k === "toggle")
                  update.mutate({ id: p.id, data: { active: !p.active } });
                else if (k === "delete") setToDelete(p);
              }}
            >
              <Dropdown.Item id="edit">Edit</Dropdown.Item>
              <Dropdown.Item id="toggle">
                {p.active ? "Deactivate" : "Activate"}
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
        title="Popups"
        description="Timed and targeted popups shown to visitors."
        actions={
          <Button variant="primary" size="sm" onPress={() => setEditing({ ...EMPTY })}>
            New popup
          </Button>
        }
      />

      <DataTableToolbar
        search={q}
        onSearch={(v) => {
          setQ(v);
          setPage(1);
        }}
        searchPlaceholder="Search popups…"
      />

      {isLoading ? (
        <LoadingState />
      ) : isError ? (
        <ErrorState message={errMessage(error)} />
      ) : items.length === 0 ? (
        <AdminEmptyState
          title="No popups yet"
          action={
            <Button variant="primary" onPress={() => setEditing({ ...EMPTY })}>
              New popup
            </Button>
          }
        />
      ) : (
        <>
          <AdminTable columns={columns} rows={items} ariaLabel="Popups" />
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
        title={editing?.id ? "Edit popup" : "New popup"}
        onSave={save}
        isSaving={create.isPending || update.isPending}
      >
        {editing && (
          <>
            <LocalizedInput
              label="Title"
              value={editing.title}
              onChange={(v) => setField("title", v)}
            />
            <LocalizedInput
              label="Body"
              multiline
              rows={4}
              value={editing.body}
              onChange={(v) => setField("body", v)}
            />
            <MediaPicker
              label="Media"
              value={editing.mediaId}
              onChange={(id) => setField("mediaId", id)}
            />
            <FormCard title="Call to action" description="Optional button on the popup.">
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
            <SelectInput
              label="Frequency"
              value={editing.frequency}
              onChange={(v) => setField("frequency", v as AdminPopup["frequency"])}
              options={POPUP_FREQUENCY_OPTIONS}
            />
            {editing.frequency === "custom_days" && (
              <NumberInput
                label="Frequency days"
                value={editing.frequencyDays}
                onChange={(v) => setField("frequencyDays", v)}
                min={1}
              />
            )}
            <SelectInput
              label="Audience"
              value={editing.audience}
              onChange={(v) => setField("audience", v as AdminPopup["audience"])}
              options={AUDIENCE_OPTIONS}
            />
            <NumberInput
              label="Delay (seconds)"
              value={editing.delaySeconds}
              onChange={(v) => setField("delaySeconds", v)}
              min={0}
            />
            <NumberInput
              label="Scroll depth (%)"
              value={editing.scrollDepthPercent}
              onChange={(v) => setField("scrollDepthPercent", v)}
              min={0}
              max={100}
            />
            <SwitchInput
              label="Exit intent"
              value={!!editing.exitIntent}
              onChange={(v) => setField("exitIntent", v)}
            />
            <SwitchInput
              label="Dismissible"
              value={!!editing.dismissible}
              onChange={(v) => setField("dismissible", v)}
            />
            <NumberInput
              label="Priority"
              value={editing.priority}
              onChange={(v) => setField("priority", v)}
            />
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
            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium text-foreground">Device targets</span>
              <div className="flex flex-wrap gap-4">
                <CheckboxInput
                  label="Desktop"
                  value={editing.deviceTargets?.includes("desktop") ?? false}
                  onChange={(v) => toggleDevice("desktop", v)}
                />
                <CheckboxInput
                  label="Mobile"
                  value={editing.deviceTargets?.includes("mobile") ?? false}
                  onChange={(v) => toggleDevice("mobile", v)}
                />
              </div>
            </div>
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
        title="Delete popup?"
        body={`"${toDelete ? tx(toDelete.title) : ""}" will be permanently removed.`}
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
