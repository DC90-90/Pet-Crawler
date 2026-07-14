import { useState } from "react";
import { Button, Dropdown } from "@heroui/react";
import {
  galleryAlbumsApi,
  tx,
  errMessage,
  type AdminGalleryAlbum,
} from "@/lib/admin";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { DataTableToolbar, Pager } from "@/components/admin/DataTableToolbar";
import { PublishedChip } from "@/components/admin/StatusChip";
import { ConfirmDialog } from "@/components/admin/ConfirmDialog";
import { EditorModal } from "@/components/admin/EditorModal";
import { LocalizedInput } from "@/components/admin/LocalizedInput";
import { MediaPicker, MediaMultiPicker } from "@/components/admin/MediaPicker";
import {
  LoadingState,
  ErrorState,
  AdminEmptyState,
} from "@/components/admin/AdminEmptyState";
import { TextInput, NumberInput, SwitchInput } from "@/components/admin/FormField";

const PAGE_SIZE = 20;
const EMPTY: Partial<AdminGalleryAlbum> = {
  title: { en: "" },
  slug: "",
  published: false,
};

export function Component() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Partial<AdminGalleryAlbum> | null>(
    null,
  );
  const [toDelete, setToDelete] = useState<AdminGalleryAlbum | null>(null);

  const { data, isLoading, isError, error } = galleryAlbumsApi.useList({
    q,
    page,
    pageSize: PAGE_SIZE,
  });
  const create = galleryAlbumsApi.useCreate();
  const update = galleryAlbumsApi.useUpdate();
  const remove = galleryAlbumsApi.useRemove();

  const items = data?.items ?? [];
  const setField = <K extends keyof AdminGalleryAlbum>(
    k: K,
    v: AdminGalleryAlbum[K],
  ) => setEditing((e) => (e ? { ...e, [k]: v } : e));

  const save = () => {
    if (!editing) return;
    if (editing.id)
      update.mutate(
        { id: editing.id, data: editing },
        { onSuccess: () => setEditing(null) },
      );
    else create.mutate(editing, { onSuccess: () => setEditing(null) });
  };

  const columns: Column<AdminGalleryAlbum>[] = [
    {
      key: "title",
      header: "Title",
      render: (a) => (
        <button
          type="button"
          onClick={() => setEditing(a)}
          className="text-start font-medium text-foreground hover:text-copper"
        >
          {tx(a.title) || a.slug}
        </button>
      ),
    },
    {
      key: "slug",
      header: "Slug",
      render: (a) => <span className="text-sm text-muted">{a.slug}</span>,
    },
    {
      key: "images",
      header: "Images",
      render: (a) => (
        <span className="text-sm text-muted">{a.mediaIds?.length ?? 0}</span>
      ),
    },
    {
      key: "published",
      header: "Published",
      render: (a) => <PublishedChip published={a.published} />,
    },
    {
      key: "actions",
      header: "",
      align: "end",
      render: (a) => (
        <Dropdown>
            <Button variant="outline" size="sm" isIconOnly aria-label="Actions">
              ⋯
            </Button>
          <Dropdown.Popover>
            <Dropdown.Menu
              onAction={(key) => {
                const k = String(key);
                if (k === "edit") setEditing(a);
                else if (k === "toggle")
                  update.mutate({
                    id: a.id,
                    data: { published: !a.published },
                  });
                else if (k === "delete") setToDelete(a);
              }}
            >
              <Dropdown.Item id="edit">Edit</Dropdown.Item>
              <Dropdown.Item id="toggle">
                {a.published ? "Unpublish" : "Publish"}
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
        title="Gallery"
        description="Photo albums for the gallery."
        actions={
          <Button
            variant="primary"
            size="sm"
            onPress={() => setEditing({ ...EMPTY })}
          >
            New album
          </Button>
        }
      />

      <DataTableToolbar
        search={q}
        onSearch={(v) => {
          setQ(v);
          setPage(1);
        }}
        searchPlaceholder="Search albums…"
      />

      {isLoading ? (
        <LoadingState />
      ) : isError ? (
        <ErrorState message={errMessage(error)} />
      ) : items.length === 0 ? (
        <AdminEmptyState
          title="No albums yet"
          description="Create a photo album for the gallery."
          action={
            <Button variant="primary" onPress={() => setEditing({ ...EMPTY })}>
              New album
            </Button>
          }
        />
      ) : (
        <>
          <AdminTable columns={columns} rows={items} ariaLabel="Gallery albums" />
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
        title={editing?.id ? "Edit album" : "New album"}
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
              label="Title"
              value={editing.title}
              onChange={(v) => setField("title", v)}
            />
            <TextInput
              label="Category"
              value={editing.category ?? ""}
              onChange={(v) => setField("category", v || undefined)}
            />
            <MediaPicker
              label="Cover image"
              value={editing.coverMediaId}
              onChange={(id) => setField("coverMediaId", id)}
            />
            <MediaMultiPicker
              label="Images"
              value={editing.mediaIds ?? []}
              onChange={(ids) => setField("mediaIds", ids)}
            />
            <NumberInput
              label="Display order"
              value={editing.displayOrder}
              onChange={(v) => setField("displayOrder", v)}
              min={0}
            />
            <SwitchInput
              label="Published"
              value={!!editing.published}
              onChange={(v) => setField("published", v)}
            />
          </>
        )}
      </EditorModal>

      <ConfirmDialog
        isOpen={!!toDelete}
        onOpenChange={(open) => !open && setToDelete(null)}
        title="Delete album?"
        body={`"${toDelete ? tx(toDelete.title) || toDelete.slug : ""}" will be permanently removed.`}
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
