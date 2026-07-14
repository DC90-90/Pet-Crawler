import { useState } from "react";
import { Button, Dropdown, Chip } from "@heroui/react";
import { videosApi, tx, errMessage, type AdminVideo } from "@/lib/admin";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { DataTableToolbar, Pager } from "@/components/admin/DataTableToolbar";
import { PublishedChip } from "@/components/admin/StatusChip";
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
  TextInput,
  NumberInput,
  SelectInput,
  SwitchInput,
} from "@/components/admin/FormField";
import { VIDEO_KIND_OPTIONS } from "@/components/admin/constants";

const PAGE_SIZE = 20;
const EMPTY: Partial<AdminVideo> = {
  title: { en: "" },
  kind: "uploaded",
  featured: false,
  published: false,
};

export function Component() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Partial<AdminVideo> | null>(null);
  const [toDelete, setToDelete] = useState<AdminVideo | null>(null);

  const { data, isLoading, isError, error } = videosApi.useList({
    q,
    page,
    pageSize: PAGE_SIZE,
  });
  const create = videosApi.useCreate();
  const update = videosApi.useUpdate();
  const remove = videosApi.useRemove();

  const items = data?.items ?? [];
  const setField = <K extends keyof AdminVideo>(k: K, v: AdminVideo[K]) =>
    setEditing((e) => (e ? { ...e, [k]: v } : e));

  const save = () => {
    if (!editing) return;
    if (editing.id)
      update.mutate(
        { id: editing.id, data: editing },
        { onSuccess: () => setEditing(null) },
      );
    else create.mutate(editing, { onSuccess: () => setEditing(null) });
  };

  const columns: Column<AdminVideo>[] = [
    {
      key: "title",
      header: "Title",
      render: (v) => (
        <button
          type="button"
          onClick={() => setEditing(v)}
          className="text-start font-medium text-foreground hover:text-copper"
        >
          {tx(v.title) || "(untitled)"}
        </button>
      ),
    },
    {
      key: "kind",
      header: "Kind",
      render: (v) => <span className="text-sm text-muted">{v.kind}</span>,
    },
    {
      key: "published",
      header: "Published",
      render: (v) => <PublishedChip published={v.published} />,
    },
    {
      key: "featured",
      header: "Featured",
      render: (v) =>
        v.featured ? (
          <Chip variant="soft" size="sm" color="accent">
            Featured
          </Chip>
        ) : (
          <span className="text-sm text-muted">—</span>
        ),
    },
    {
      key: "actions",
      header: "",
      align: "end",
      render: (v) => (
        <Dropdown>
            <Button variant="outline" size="sm" isIconOnly aria-label="Actions">
              ⋯
            </Button>
          <Dropdown.Popover>
            <Dropdown.Menu
              onAction={(key) => {
                const k = String(key);
                if (k === "edit") setEditing(v);
                else if (k === "toggle")
                  update.mutate({
                    id: v.id,
                    data: { published: !v.published },
                  });
                else if (k === "delete") setToDelete(v);
              }}
            >
              <Dropdown.Item id="edit">Edit</Dropdown.Item>
              <Dropdown.Item id="toggle">
                {v.published ? "Unpublish" : "Publish"}
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
        title="Videos"
        description="Uploaded and embedded videos for the site."
        actions={
          <Button
            variant="primary"
            size="sm"
            onPress={() => setEditing({ ...EMPTY })}
          >
            New video
          </Button>
        }
      />

      <DataTableToolbar
        search={q}
        onSearch={(v) => {
          setQ(v);
          setPage(1);
        }}
        searchPlaceholder="Search videos…"
      />

      {isLoading ? (
        <LoadingState />
      ) : isError ? (
        <ErrorState message={errMessage(error)} />
      ) : items.length === 0 ? (
        <AdminEmptyState
          title="No videos yet"
          description="Add an uploaded or embedded video."
          action={
            <Button variant="primary" onPress={() => setEditing({ ...EMPTY })}>
              New video
            </Button>
          }
        />
      ) : (
        <>
          <AdminTable columns={columns} rows={items} ariaLabel="Videos" />
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
        title={editing?.id ? "Edit video" : "New video"}
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
              label="Caption"
              multiline
              rows={2}
              value={editing.caption}
              onChange={(v) => setField("caption", v)}
            />
            <SelectInput
              label="Kind"
              value={editing.kind}
              onChange={(v) => setField("kind", v as AdminVideo["kind"])}
              options={VIDEO_KIND_OPTIONS}
            />
            {editing.kind === "uploaded" ? (
              <MediaPicker
                label="Video file"
                value={editing.mediaId}
                onChange={(id) => setField("mediaId", id)}
              />
            ) : (
              <TextInput
                label="Video URL"
                type="url"
                value={editing.externalUrl ?? ""}
                onChange={(v) => setField("externalUrl", v || undefined)}
              />
            )}
            <MediaPicker
              label="Poster image"
              value={editing.posterMediaId}
              onChange={(id) => setField("posterMediaId", id)}
              hint="Thumbnail shown before playback."
            />
            <NumberInput
              label="Display order"
              value={editing.displayOrder}
              onChange={(v) => setField("displayOrder", v)}
              min={0}
            />
            <div className="flex flex-wrap gap-4">
              <SwitchInput
                label="Featured"
                value={!!editing.featured}
                onChange={(v) => setField("featured", v)}
              />
              <SwitchInput
                label="Published"
                value={!!editing.published}
                onChange={(v) => setField("published", v)}
              />
            </div>
          </>
        )}
      </EditorModal>

      <ConfirmDialog
        isOpen={!!toDelete}
        onOpenChange={(open) => !open && setToDelete(null)}
        title="Delete video?"
        body={`"${toDelete ? tx(toDelete.title) : ""}" will be permanently removed.`}
        destructive
        confirmLabel="Delete"
        isPending={remove.isPending}
        onConfirm={() =>
          toDelete &&
          remove.mutate(toDelete.id, { onSuccess: () => setToDelete(null) })
        }
      />
    </div>
  );
}
