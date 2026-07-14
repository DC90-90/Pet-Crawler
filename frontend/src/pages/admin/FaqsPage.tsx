import { useState } from "react";
import { Button, Dropdown } from "@heroui/react";
import { faqsApi, tx, errMessage, type AdminFaq } from "@/lib/admin";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { PublishedChip } from "@/components/admin/StatusChip";
import { ConfirmDialog } from "@/components/admin/ConfirmDialog";
import { EditorModal } from "@/components/admin/EditorModal";
import { LocalizedInput } from "@/components/admin/LocalizedInput";
import {
  LoadingState,
  ErrorState,
  AdminEmptyState,
} from "@/components/admin/AdminEmptyState";
import { TextInput, NumberInput, SwitchInput } from "@/components/admin/FormField";

const EMPTY: Partial<AdminFaq> = {
  question: { en: "" },
  answer: { en: "" },
  category: "",
  published: false,
};

export function Component() {
  const [editing, setEditing] = useState<Partial<AdminFaq> | null>(null);
  const [toDelete, setToDelete] = useState<AdminFaq | null>(null);

  const { data, isLoading, isError, error } = faqsApi.useList({ pageSize: 200 });
  const create = faqsApi.useCreate();
  const update = faqsApi.useUpdate();
  const remove = faqsApi.useRemove();

  const items = data?.items ?? [];
  const setField = <K extends keyof AdminFaq>(k: K, v: AdminFaq[K]) =>
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

  // Group items by category, then sort each group by displayOrder.
  const groups = new Map<string, AdminFaq[]>();
  for (const f of items) {
    const key = f.category || "Uncategorized";
    const arr = groups.get(key);
    if (arr) arr.push(f);
    else groups.set(key, [f]);
  }
  const orderedGroups = [...groups.entries()]
    .map(([category, rows]) => ({
      category,
      rows: [...rows].sort(
        (a, b) => (a.displayOrder ?? 0) - (b.displayOrder ?? 0),
      ),
    }))
    .sort((a, b) => a.category.localeCompare(b.category));

  return (
    <div>
      <AdminPageHeader
        title="FAQs"
        description="Frequently asked questions, grouped by category."
        actions={
          <Button
            variant="primary"
            size="sm"
            onPress={() => setEditing({ ...EMPTY })}
          >
            New FAQ
          </Button>
        }
      />

      {isLoading ? (
        <LoadingState />
      ) : isError ? (
        <ErrorState message={errMessage(error)} />
      ) : items.length === 0 ? (
        <AdminEmptyState
          title="No FAQs yet"
          description="Add a frequently asked question."
          action={
            <Button variant="primary" onPress={() => setEditing({ ...EMPTY })}>
              New FAQ
            </Button>
          }
        />
      ) : (
        <div className="flex flex-col gap-8">
          {orderedGroups.map((group) => (
            <section key={group.category}>
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">
                {group.category}
              </h2>
              <div className="overflow-hidden rounded-lg border border-border bg-surface">
                <ul className="divide-y divide-border">
                  {group.rows.map((f) => (
                    <li
                      key={f.id}
                      className="flex items-center gap-3 px-4 py-3"
                    >
                      <button
                        type="button"
                        onClick={() => setEditing(f)}
                        className="flex-1 text-start font-medium text-foreground hover:text-copper"
                      >
                        {tx(f.question) || "(untitled)"}
                      </button>
                      <PublishedChip published={f.published} />
                      <Dropdown>
                          <Button
                            variant="outline"
                            size="sm"
                            isIconOnly
                            aria-label="Actions"
                          >
                            ⋯
                          </Button>
                        <Dropdown.Popover>
                          <Dropdown.Menu
                            onAction={(key) => {
                              const k = String(key);
                              if (k === "edit") setEditing(f);
                              else if (k === "toggle")
                                update.mutate({
                                  id: f.id,
                                  data: { published: !f.published },
                                });
                              else if (k === "delete") setToDelete(f);
                            }}
                          >
                            <Dropdown.Item id="edit">Edit</Dropdown.Item>
                            <Dropdown.Item id="toggle">
                              {f.published ? "Unpublish" : "Publish"}
                            </Dropdown.Item>
                            <Dropdown.Item id="delete">Delete</Dropdown.Item>
                          </Dropdown.Menu>
                        </Dropdown.Popover>
                      </Dropdown>
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          ))}
        </div>
      )}

      <EditorModal
        isOpen={!!editing}
        onOpenChange={(open) => !open && setEditing(null)}
        title={editing?.id ? "Edit FAQ" : "New FAQ"}
        onSave={save}
        isSaving={create.isPending || update.isPending}
      >
        {editing && (
          <>
            <LocalizedInput
              label="Question"
              value={editing.question}
              onChange={(v) => setField("question", v)}
            />
            <LocalizedInput
              label="Answer"
              multiline
              rows={5}
              value={editing.answer}
              onChange={(v) => setField("answer", v)}
            />
            <TextInput
              label="Category"
              value={editing.category ?? ""}
              onChange={(v) => setField("category", v)}
              isRequired
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
        title="Delete FAQ?"
        body={`"${toDelete ? tx(toDelete.question) : ""}" will be permanently removed.`}
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
