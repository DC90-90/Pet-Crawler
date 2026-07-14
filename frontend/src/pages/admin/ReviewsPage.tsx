import { useState } from "react";
import { Button, Dropdown, Alert } from "@heroui/react";
import { reviewsApi, errMessage, type AdminReview } from "@/lib/admin";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { DataTableToolbar, Pager } from "@/components/admin/DataTableToolbar";
import { PublishedChip } from "@/components/admin/StatusChip";
import { ConfirmDialog } from "@/components/admin/ConfirmDialog";
import { EditorModal } from "@/components/admin/EditorModal";
import {
  LoadingState,
  ErrorState,
  AdminEmptyState,
} from "@/components/admin/AdminEmptyState";
import {
  FieldGrid,
  TextInput,
  TextAreaInput,
  NumberInput,
  SelectInput,
  SwitchInput,
} from "@/components/admin/FormField";
import { REVIEW_SOURCE_OPTIONS } from "@/components/admin/constants";
import { Stars, SampleFlag } from "@/components/primitives";

const PAGE_SIZE = 20;
const EMPTY: Partial<AdminReview> = {
  reviewerName: "",
  rating: 5,
  text: "",
  source: "manual",
  published: false,
  isSample: false,
};

export function Component() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Partial<AdminReview> | null>(null);
  const [toDelete, setToDelete] = useState<AdminReview | null>(null);

  const { data, isLoading, isError, error } = reviewsApi.useList({
    q,
    page,
    pageSize: PAGE_SIZE,
  });
  const create = reviewsApi.useCreate();
  const update = reviewsApi.useUpdate();
  const remove = reviewsApi.useRemove();

  const items = data?.items ?? [];
  const setField = <K extends keyof AdminReview>(k: K, v: AdminReview[K]) =>
    setEditing((e) => (e ? { ...e, [k]: v } : e));

  const save = () => {
    if (!editing) return;
    if (editing.id)
      update.mutate({ id: editing.id, data: editing }, { onSuccess: () => setEditing(null) });
    else create.mutate(editing, { onSuccess: () => setEditing(null) });
  };

  const columns: Column<AdminReview>[] = [
    {
      key: "reviewer",
      header: "Reviewer",
      render: (r) => (
        <button
          type="button"
          onClick={() => setEditing(r)}
          className="flex flex-col items-start text-start hover:text-copper"
        >
          <span className="font-medium text-foreground">{r.reviewerName}</span>
          {r.country && <span className="text-xs text-muted">{r.country}</span>}
        </button>
      ),
    },
    { key: "rating", header: "Rating", render: (r) => <Stars rating={r.rating} /> },
    {
      key: "source",
      header: "Source",
      render: (r) => (
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted">{r.source}</span>
          <SampleFlag show={r.isSample} />
        </div>
      ),
    },
    {
      key: "published",
      header: "Published",
      render: (r) => <PublishedChip published={r.published} />,
    },
    {
      key: "actions",
      header: "",
      align: "end",
      render: (r) => (
        <Dropdown>
            <Button variant="outline" size="sm" isIconOnly aria-label="Actions">
              ⋯
            </Button>
          <Dropdown.Popover>
            <Dropdown.Menu
              onAction={(key) => {
                const k = String(key);
                if (k === "edit") setEditing(r);
                else if (k === "toggle")
                  update.mutate({ id: r.id, data: { published: !r.published } });
                else if (k === "delete") setToDelete(r);
              }}
            >
              <Dropdown.Item id="edit">Edit</Dropdown.Item>
              <Dropdown.Item id="toggle">
                {r.published ? "Unpublish" : "Publish"}
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
        title="Reviews"
        description="Guest reviews are added manually only — never auto-generated."
        actions={
          <Button variant="primary" size="sm" onPress={() => setEditing({ ...EMPTY })}>
            Add review
          </Button>
        }
      />

      <Alert color="warning" className="mb-4">
        <Alert.Indicator />
        <Alert.Content>
          <Alert.Title>Manual entry only</Alert.Title>
          <Alert.Description>
            Reviews must reflect real guests. Sample reviews (isSample) are for development
            and are excluded from the production public site.
          </Alert.Description>
        </Alert.Content>
      </Alert>

      <DataTableToolbar
        search={q}
        onSearch={(v) => {
          setQ(v);
          setPage(1);
        }}
        searchPlaceholder="Search reviews…"
      />

      {isLoading ? (
        <LoadingState />
      ) : isError ? (
        <ErrorState message={errMessage(error)} />
      ) : items.length === 0 ? (
        <AdminEmptyState
          title="No reviews yet"
          description="Add a review from a real guest."
          icon="★"
          action={
            <Button variant="primary" onPress={() => setEditing({ ...EMPTY })}>
              Add review
            </Button>
          }
        />
      ) : (
        <>
          <AdminTable columns={columns} rows={items} ariaLabel="Reviews" />
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
        title={editing?.id ? "Edit review" : "Add review"}
        onSave={save}
        isSaving={create.isPending || update.isPending}
      >
        {editing && (
          <>
            <FieldGrid>
              <TextInput
                label="Reviewer name"
                value={editing.reviewerName ?? ""}
                onChange={(v) => setField("reviewerName", v)}
                isRequired
              />
              <TextInput
                label="Country"
                value={editing.country ?? ""}
                onChange={(v) => setField("country", v)}
              />
              <NumberInput
                label="Rating (1–5)"
                value={editing.rating}
                onChange={(v) => setField("rating", v ?? 5)}
                min={1}
                max={5}
              />
              <TextInput
                label="Date"
                type="date"
                value={editing.date ?? ""}
                onChange={(v) => setField("date", v || undefined)}
              />
              <SelectInput
                label="Source"
                value={editing.source}
                onChange={(v) => setField("source", v as AdminReview["source"])}
                options={REVIEW_SOURCE_OPTIONS}
              />
              <TextInput
                label="Source URL"
                value={editing.sourceUrl ?? ""}
                onChange={(v) => setField("sourceUrl", v || undefined)}
              />
            </FieldGrid>
            <TextAreaInput
              label="Review text"
              value={editing.text ?? ""}
              onChange={(v) => setField("text", v)}
              rows={4}
            />
            <div className="flex flex-wrap gap-4">
              <SwitchInput
                label="Published"
                value={!!editing.published}
                onChange={(v) => setField("published", v)}
              />
              <SwitchInput
                label="Featured"
                value={!!editing.featured}
                onChange={(v) => setField("featured", v)}
              />
              <SwitchInput
                label="Sample (dev only)"
                value={!!editing.isSample}
                onChange={(v) => setField("isSample", v)}
              />
            </div>
          </>
        )}
      </EditorModal>

      <ConfirmDialog
        isOpen={!!toDelete}
        onOpenChange={(open) => !open && setToDelete(null)}
        title="Delete review?"
        body={`Review from "${toDelete?.reviewerName ?? ""}" will be removed.`}
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
