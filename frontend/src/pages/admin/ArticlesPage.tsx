import { useState } from "react";
import { Button, Dropdown } from "@heroui/react";
import { articlesApi, tx, errMessage, type AdminArticle } from "@/lib/admin";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { DataTableToolbar, Pager } from "@/components/admin/DataTableToolbar";
import { StatusChip } from "@/components/admin/StatusChip";
import { ConfirmDialog } from "@/components/admin/ConfirmDialog";
import { EditorModal } from "@/components/admin/EditorModal";
import { LocalizedInput } from "@/components/admin/LocalizedInput";
import { MediaPicker } from "@/components/admin/MediaPicker";
import {
  LoadingState,
  ErrorState,
  AdminEmptyState,
} from "@/components/admin/AdminEmptyState";
import { TextInput, TagsInput, NumberInput } from "@/components/admin/FormField";

const PAGE_SIZE = 20;
const EMPTY: Partial<AdminArticle> = {
  status: "draft",
  title: { en: "" },
  excerpt: { en: "" },
};

export function Component() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Partial<AdminArticle> | null>(null);
  const [toDelete, setToDelete] = useState<AdminArticle | null>(null);

  const { data, isLoading, isError, error } = articlesApi.useList({
    q,
    page,
    pageSize: PAGE_SIZE,
  });
  const create = articlesApi.useCreate();
  const update = articlesApi.useUpdate();
  const remove = articlesApi.useRemove();
  const publish = articlesApi.usePublish();
  const unpublish = articlesApi.useUnpublish();

  const items = data?.items ?? [];
  const setField = <K extends keyof AdminArticle>(k: K, v: AdminArticle[K]) =>
    setEditing((e) => (e ? { ...e, [k]: v } : e));

  const save = () => {
    if (!editing) return;
    if (editing.id)
      update.mutate({ id: editing.id, data: editing }, { onSuccess: () => setEditing(null) });
    else create.mutate(editing, { onSuccess: () => setEditing(null) });
  };

  const columns: Column<AdminArticle>[] = [
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
    { key: "status", header: "Status", render: (a) => <StatusChip status={a.status} /> },
    {
      key: "author",
      header: "Author",
      render: (a) => <span className="text-sm text-muted">{a.author ?? "—"}</span>,
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
                else if (k === "publish") publish.mutate(a.id);
                else if (k === "unpublish") unpublish.mutate(a.id);
                else if (k === "delete") setToDelete(a);
              }}
            >
              <Dropdown.Item id="edit">Edit</Dropdown.Item>
              {a.status === "published" ? (
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
        title="Travel Guide"
        description="Articles and stories for the travel guide."
        actions={
          <Button variant="primary" size="sm" onPress={() => setEditing({ ...EMPTY })}>
            New article
          </Button>
        }
      />

      <DataTableToolbar
        search={q}
        onSearch={(v) => {
          setQ(v);
          setPage(1);
        }}
        searchPlaceholder="Search articles…"
      />

      {isLoading ? (
        <LoadingState />
      ) : isError ? (
        <ErrorState message={errMessage(error)} />
      ) : items.length === 0 ? (
        <AdminEmptyState
          title="No articles yet"
          action={
            <Button variant="primary" onPress={() => setEditing({ ...EMPTY })}>
              New article
            </Button>
          }
        />
      ) : (
        <>
          <AdminTable columns={columns} rows={items} ariaLabel="Articles" />
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
        title={editing?.id ? "Edit article" : "New article"}
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
            <LocalizedInput
              label="Excerpt"
              multiline
              rows={2}
              value={editing.excerpt}
              onChange={(v) => setField("excerpt", v)}
            />
            <LocalizedInput
              label="Body"
              multiline
              rows={8}
              value={editing.body}
              onChange={(v) => setField("body", v)}
              hint="Rich text is sanitized server-side."
            />
            <MediaPicker
              label="Cover image"
              value={editing.coverMediaId}
              onChange={(id) => setField("coverMediaId", id)}
            />
            <TextInput
              label="Author"
              value={editing.author ?? ""}
              onChange={(v) => setField("author", v)}
            />
            <TagsInput
              label="Categories"
              value={editing.categories ?? []}
              onChange={(v) => setField("categories", v)}
            />
            <TagsInput
              label="Tags"
              value={editing.tags ?? []}
              onChange={(v) => setField("tags", v)}
            />
            <NumberInput
              label="Reading minutes"
              value={editing.readingMinutes}
              onChange={(v) => setField("readingMinutes", v)}
              min={0}
            />
          </>
        )}
      </EditorModal>

      <ConfirmDialog
        isOpen={!!toDelete}
        onOpenChange={(open) => !open && setToDelete(null)}
        title="Delete article?"
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
