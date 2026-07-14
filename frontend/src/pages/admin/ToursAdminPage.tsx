import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Chip, Dropdown } from "@heroui/react";
import {
  toursApi,
  tx,
  errMessage,
  type AdminTour,
} from "@/lib/admin";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { DataTableToolbar, Pager } from "@/components/admin/DataTableToolbar";
import { StatusChip } from "@/components/admin/StatusChip";
import { ConfirmDialog } from "@/components/admin/ConfirmDialog";
import {
  LoadingState,
  ErrorState,
  AdminEmptyState,
} from "@/components/admin/AdminEmptyState";
import { STATUS_FILTER_OPTIONS } from "@/components/admin/constants";

const PAGE_SIZE = 20;

export function Component() {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [toDelete, setToDelete] = useState<AdminTour | null>(null);

  const { data, isLoading, isError, error } = toursApi.useList({
    q,
    status,
    page,
    pageSize: PAGE_SIZE,
  });
  const publish = toursApi.usePublish();
  const unpublish = toursApi.useUnpublish();
  const remove = toursApi.useRemove();

  const handleAction = (key: string, tour: AdminTour) => {
    if (key === "edit") navigate(`/admin/tours/${tour.id}`);
    else if (key === "publish") publish.mutate(tour.id);
    else if (key === "unpublish") unpublish.mutate(tour.id);
    else if (key === "delete") setToDelete(tour);
  };

  const columns: Column<AdminTour>[] = [
    {
      key: "name",
      header: "Name",
      render: (t) => (
        <button
          type="button"
          onClick={() => navigate(`/admin/tours/${t.id}`)}
          className="text-start font-medium text-foreground hover:text-copper"
        >
          {tx(t.name) || t.slug || "(untitled)"}
        </button>
      ),
    },
    { key: "status", header: "Status", render: (t) => <StatusChip status={t.status} /> },
    {
      key: "type",
      header: "Type",
      render: (t) => <span className="text-sm text-muted">{t.tourType ?? "—"}</span>,
    },
    {
      key: "featured",
      header: "Featured",
      render: (t) =>
        t.featured ? (
          <Chip size="sm" variant="soft" color="accent">
            Featured
          </Chip>
        ) : (
          <span className="text-muted">—</span>
        ),
    },
    {
      key: "updated",
      header: "Updated",
      render: (t) => (
        <span className="text-sm text-muted">
          {t.updatedAt ? new Date(t.updatedAt).toLocaleDateString() : "—"}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      align: "end",
      render: (t) => (
        <Dropdown>
            <Button variant="outline" size="sm" isIconOnly aria-label={`Actions for ${tx(t.name)}`}>
              ⋯
            </Button>
          <Dropdown.Popover>
            <Dropdown.Menu onAction={(key) => handleAction(String(key), t)}>
              <Dropdown.Item id="edit">Edit</Dropdown.Item>
              {t.status === "published" ? (
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

  const items = data?.items ?? [];

  return (
    <div>
      <AdminPageHeader
        title="Tours"
        description="Curated experiences across Svaneti."
        actions={
          <Button variant="primary" size="sm" onPress={() => navigate("/admin/tours/new")}>
            New tour
          </Button>
        }
      />

      <DataTableToolbar
        search={q}
        onSearch={(v) => {
          setQ(v);
          setPage(1);
        }}
        searchPlaceholder="Search tours…"
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
          title="No tours yet"
          description="Create your first tour to start building the catalogue."
          action={
            <Button variant="primary" onPress={() => navigate("/admin/tours/new")}>
              New tour
            </Button>
          }
        />
      ) : (
        <>
          <AdminTable columns={columns} rows={items} ariaLabel="Tours" />
          <Pager
            page={data?.page ?? page}
            pageSize={data?.pageSize ?? PAGE_SIZE}
            total={data?.total ?? items.length}
            onPage={setPage}
          />
        </>
      )}

      <ConfirmDialog
        isOpen={!!toDelete}
        onOpenChange={(open) => !open && setToDelete(null)}
        title="Delete tour?"
        body={`"${toDelete ? tx(toDelete.name) : ""}" will be permanently removed. This cannot be undone.`}
        confirmLabel="Delete"
        destructive
        isPending={remove.isPending}
        onConfirm={() => {
          if (!toDelete) return;
          remove.mutate(toDelete.id, { onSuccess: () => setToDelete(null) });
        }}
      />
    </div>
  );
}
