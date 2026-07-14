import { useState } from "react";
import { Button, Dropdown, Chip } from "@heroui/react";
import { offersApi, tx, errMessage, type AdminOffer } from "@/lib/admin";
import type { Cta } from "@/lib/types";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { DataTableToolbar, Pager } from "@/components/admin/DataTableToolbar";
import { StatusChip } from "@/components/admin/StatusChip";
import { ConfirmDialog } from "@/components/admin/ConfirmDialog";
import { EditorModal } from "@/components/admin/EditorModal";
import { LocalizedInput } from "@/components/admin/LocalizedInput";
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
import {
  STATUS_FILTER_OPTIONS,
  DISCOUNT_TYPE_OPTIONS,
} from "@/components/admin/constants";

const PAGE_SIZE = 20;
const EMPTY: Partial<AdminOffer> = {
  status: "draft",
  title: { en: "" },
  description: { en: "" },
};

function discountLabel(o: AdminOffer): string {
  if (o.discountValue === undefined) return "—";
  return `${o.discountValue}${o.discountType === "percent" ? "%" : ""}`;
}

export function Component() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Partial<AdminOffer> | null>(null);
  const [toDelete, setToDelete] = useState<AdminOffer | null>(null);

  const { data, isLoading, isError, error } = offersApi.useList({
    q,
    status: status || undefined,
    page,
    pageSize: PAGE_SIZE,
  });
  const create = offersApi.useCreate();
  const update = offersApi.useUpdate();
  const remove = offersApi.useRemove();
  const publish = offersApi.usePublish();
  const unpublish = offersApi.useUnpublish();

  const items = data?.items ?? [];
  const setField = <K extends keyof AdminOffer>(k: K, v: AdminOffer[K]) =>
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

  const columns: Column<AdminOffer>[] = [
    {
      key: "title",
      header: "Title",
      render: (o) => (
        <button
          type="button"
          onClick={() => setEditing(o)}
          className="text-start font-medium text-foreground hover:text-copper"
        >
          {tx(o.title) || "Untitled"}
        </button>
      ),
    },
    { key: "status", header: "Status", render: (o) => <StatusChip status={o.status} /> },
    {
      key: "discount",
      header: "Discount",
      render: (o) => <span className="text-sm text-muted">{discountLabel(o)}</span>,
    },
    {
      key: "featured",
      header: "Featured",
      render: (o) =>
        o.featured ? (
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
      render: (o) => (
        <Dropdown>
            <Button variant="outline" size="sm" isIconOnly aria-label="Actions">
              ⋯
            </Button>
          <Dropdown.Popover>
            <Dropdown.Menu
              onAction={(key) => {
                const k = String(key);
                if (k === "edit") setEditing(o);
                else if (k === "publish") publish.mutate(o.id);
                else if (k === "unpublish") unpublish.mutate(o.id);
                else if (k === "delete") setToDelete(o);
              }}
            >
              <Dropdown.Item id="edit">Edit</Dropdown.Item>
              {o.status === "published" ? (
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
        title="Offers"
        description="Discounts and promotions shown across the site."
        actions={
          <Button variant="primary" size="sm" onPress={() => setEditing({ ...EMPTY })}>
            New offer
          </Button>
        }
      />

      <DataTableToolbar
        search={q}
        onSearch={(v) => {
          setQ(v);
          setPage(1);
        }}
        searchPlaceholder="Search offers…"
        filters={[
          {
            label: "Status",
            value: status,
            onChange: (v) => {
              setStatus(v);
              setPage(1);
            },
            options: STATUS_FILTER_OPTIONS,
          },
        ]}
      />

      {isLoading ? (
        <LoadingState />
      ) : isError ? (
        <ErrorState message={errMessage(error)} />
      ) : items.length === 0 ? (
        <AdminEmptyState
          title="No offers yet"
          action={
            <Button variant="primary" onPress={() => setEditing({ ...EMPTY })}>
              New offer
            </Button>
          }
        />
      ) : (
        <>
          <AdminTable columns={columns} rows={items} ariaLabel="Offers" />
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
        title={editing?.id ? "Edit offer" : "New offer"}
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
              label="Description"
              multiline
              rows={4}
              value={editing.description}
              onChange={(v) => setField("description", v)}
            />
            <TextInput
              label="Code"
              value={editing.code ?? ""}
              onChange={(v) => setField("code", v || undefined)}
            />
            <SelectInput
              label="Discount type"
              value={editing.discountType}
              onChange={(v) => setField("discountType", v as AdminOffer["discountType"])}
              options={DISCOUNT_TYPE_OPTIONS}
            />
            <NumberInput
              label="Discount value"
              value={editing.discountValue}
              onChange={(v) => setField("discountValue", v)}
              min={0}
            />
            <LocalizedInput
              label="Terms"
              multiline
              rows={3}
              value={editing.terms}
              onChange={(v) => setField("terms", v)}
            />
            <FormCard title="Call to action" description="Optional button on the offer.">
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
            <SwitchInput
              label="Featured"
              value={!!editing.featured}
              onChange={(v) => setField("featured", v)}
            />
            <NumberInput
              label="Priority"
              value={editing.priority}
              onChange={(v) => setField("priority", v)}
            />
            <TagsInput
              label="Language targets"
              value={editing.languageTargets ?? []}
              onChange={(v) => setField("languageTargets", v)}
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
        title="Delete offer?"
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
