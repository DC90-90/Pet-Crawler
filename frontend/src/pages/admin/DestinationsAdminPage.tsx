import { useState } from "react";
import { Button, Dropdown } from "@heroui/react";
import {
  destinationsApi,
  tx,
  errMessage,
  type AdminDestination,
} from "@/lib/admin";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { DataTableToolbar, Pager } from "@/components/admin/DataTableToolbar";
import { StatusChip } from "@/components/admin/StatusChip";
import { ConfirmDialog } from "@/components/admin/ConfirmDialog";
import { EditorModal } from "@/components/admin/EditorModal";
import { LocalizedInput } from "@/components/admin/LocalizedInput";
import { MediaPicker, MediaMultiPicker } from "@/components/admin/MediaPicker";
import {
  LoadingState,
  ErrorState,
  AdminEmptyState,
} from "@/components/admin/AdminEmptyState";
import {
  FieldGrid,
  TextInput,
  NumberInput,
  TagsInput,
} from "@/components/admin/FormField";

const PAGE_SIZE = 20;
const EMPTY: Partial<AdminDestination> = {
  status: "draft",
  name: { en: "" },
  intro: { en: "" },
};

export function Component() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Partial<AdminDestination> | null>(null);
  const [toDelete, setToDelete] = useState<AdminDestination | null>(null);

  const { data, isLoading, isError, error } = destinationsApi.useList({
    q,
    page,
    pageSize: PAGE_SIZE,
  });
  const create = destinationsApi.useCreate();
  const update = destinationsApi.useUpdate();
  const remove = destinationsApi.useRemove();
  const publish = destinationsApi.usePublish();
  const unpublish = destinationsApi.useUnpublish();

  const items = data?.items ?? [];
  const isEditingExisting = !!editing?.id;

  const save = () => {
    if (!editing) return;
    if (editing.id) {
      update.mutate(
        { id: editing.id, data: editing },
        { onSuccess: () => setEditing(null) },
      );
    } else {
      create.mutate(editing, { onSuccess: () => setEditing(null) });
    }
  };

  const setField = <K extends keyof AdminDestination>(k: K, v: AdminDestination[K]) =>
    setEditing((e) => (e ? { ...e, [k]: v } : e));

  const columns: Column<AdminDestination>[] = [
    {
      key: "name",
      header: "Name",
      render: (d) => (
        <button
          type="button"
          onClick={() => setEditing(d)}
          className="text-start font-medium text-foreground hover:text-copper"
        >
          {tx(d.name) || d.slug}
        </button>
      ),
    },
    { key: "status", header: "Status", render: (d) => <StatusChip status={d.status} /> },
    {
      key: "altitude",
      header: "Altitude",
      render: (d) => (
        <span className="text-sm text-muted">{d.altitudeM ? `${d.altitudeM} m` : "—"}</span>
      ),
    },
    {
      key: "actions",
      header: "",
      align: "end",
      render: (d) => (
        <Dropdown>
            <Button variant="outline" size="sm" isIconOnly aria-label="Actions">
              ⋯
            </Button>
          <Dropdown.Popover>
            <Dropdown.Menu
              onAction={(key) => {
                const k = String(key);
                if (k === "edit") setEditing(d);
                else if (k === "publish") publish.mutate(d.id);
                else if (k === "unpublish") unpublish.mutate(d.id);
                else if (k === "delete") setToDelete(d);
              }}
            >
              <Dropdown.Item id="edit">Edit</Dropdown.Item>
              {d.status === "published" ? (
                <Dropdown.Item id="unpublish">Unpublish</Dropdown.Item>
              ) : (
                <Dropdown.Item id="publish">Publish</Dropdown.Item>
              )}
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
        title="Destinations"
        description="Places across the Svaneti region."
        actions={
          <Button variant="primary" size="sm" onPress={() => setEditing({ ...EMPTY })}>
            New destination
          </Button>
        }
      />

      <DataTableToolbar
        search={q}
        onSearch={(v) => {
          setQ(v);
          setPage(1);
        }}
        searchPlaceholder="Search destinations…"
      />

      {isLoading ? (
        <LoadingState />
      ) : isError ? (
        <ErrorState message={errMessage(error)} />
      ) : items.length === 0 ? (
        <AdminEmptyState
          title="No destinations yet"
          action={
            <Button variant="primary" onPress={() => setEditing({ ...EMPTY })}>
              New destination
            </Button>
          }
        />
      ) : (
        <>
          <AdminTable columns={columns} rows={items} ariaLabel="Destinations" />
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
        title={isEditingExisting ? "Edit destination" : "New destination"}
        onSave={save}
        isSaving={create.isPending || update.isPending}
      >
        {editing && (
          <>
            <TextInput
              label="Slug"
              value={editing.slug ?? ""}
              onChange={(v) => setField("slug", v)}
              isRequired
            />
            <LocalizedInput
              label="Name"
              value={editing.name}
              onChange={(v) => setField("name", v)}
            />
            <LocalizedInput
              label="Intro"
              multiline
              rows={2}
              value={editing.intro}
              onChange={(v) => setField("intro", v)}
            />
            <LocalizedInput
              label="Description"
              multiline
              rows={5}
              value={editing.description}
              onChange={(v) => setField("description", v)}
            />
            <MediaPicker
              label="Cover image"
              value={editing.coverMediaId}
              onChange={(id) => setField("coverMediaId", id)}
            />
            <MediaMultiPicker
              label="Gallery"
              value={editing.galleryMediaIds ?? []}
              onChange={(ids) => setField("galleryMediaIds", ids)}
            />
            <FieldGrid>
              <NumberInput
                label="Latitude"
                value={editing.coordinates?.lat}
                onChange={(v) =>
                  setField("coordinates", {
                    lat: v ?? 0,
                    lng: editing.coordinates?.lng ?? 0,
                  })
                }
              />
              <NumberInput
                label="Longitude"
                value={editing.coordinates?.lng}
                onChange={(v) =>
                  setField("coordinates", {
                    lat: editing.coordinates?.lat ?? 0,
                    lng: v ?? 0,
                  })
                }
              />
              <NumberInput
                label="Altitude (m)"
                value={editing.altitudeM}
                onChange={(v) => setField("altitudeM", v)}
              />
            </FieldGrid>
            <TagsInput
              label="Best seasons"
              value={editing.bestSeasons ?? []}
              onChange={(v) => setField("bestSeasons", v)}
            />
            <LocalizedInput
              label="Cultural notes"
              multiline
              rows={3}
              value={editing.culturalNotes}
              onChange={(v) => setField("culturalNotes", v)}
            />
            <LocalizedInput
              label="Practical advice"
              multiline
              rows={3}
              value={editing.practicalAdvice}
              onChange={(v) => setField("practicalAdvice", v)}
            />
          </>
        )}
      </EditorModal>

      <ConfirmDialog
        isOpen={!!toDelete}
        onOpenChange={(open) => !open && setToDelete(null)}
        title="Delete destination?"
        body={`"${toDelete ? tx(toDelete.name) : ""}" will be permanently removed.`}
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
