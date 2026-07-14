import { useState } from "react";
import { Chip } from "@heroui/react";
import { useAuditLogs, errMessage, type AuditLog } from "@/lib/admin";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { DataTableToolbar, Pager } from "@/components/admin/DataTableToolbar";
import {
  LoadingState,
  ErrorState,
  AdminEmptyState,
} from "@/components/admin/AdminEmptyState";

const PAGE_SIZE = 30;

type ChipColor = "accent" | "danger" | "default" | "success" | "warning";

function actionColor(action: string): ChipColor {
  switch (action) {
    case "create":
      return "accent";
    case "publish":
      return "success";
    case "unpublish":
    case "archive":
      return "warning";
    case "delete":
    case "login_failed":
      return "danger";
    case "edit":
    case "login":
    default:
      return "default";
  }
}

export function Component() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);

  const { data, isLoading, isError, error } = useAuditLogs({
    q,
    page,
    pageSize: PAGE_SIZE,
  });

  const items = data?.items ?? [];

  const columns: Column<AuditLog>[] = [
    {
      key: "at",
      header: "Time",
      render: (l) => (
        <span className="text-sm text-muted">
          {new Date(l.at).toLocaleString()}
        </span>
      ),
    },
    {
      key: "user",
      header: "User",
      render: (l) => (
        <span className="text-sm text-foreground">{l.userEmail ?? "system"}</span>
      ),
    },
    {
      key: "action",
      header: "Action",
      render: (l) => (
        <Chip variant="soft" color={actionColor(l.action)}>
          {l.action}
        </Chip>
      ),
    },
    {
      key: "entity",
      header: "Entity",
      render: (l) => (
        <span className="text-sm text-muted">
          {`${l.entity ?? ""}${l.entityId ? " · " + l.entityId.slice(0, 8) : ""}`}
        </span>
      ),
    },
    {
      key: "summary",
      header: "Summary",
      render: (l) => (
        <span className="text-sm text-foreground">{l.summary ?? "—"}</span>
      ),
    },
    {
      key: "ip",
      header: "IP",
      render: (l) => <span className="text-sm text-muted">{l.ip ?? "—"}</span>,
    },
  ];

  return (
    <div>
      <AdminPageHeader
        title="Audit log"
        description="Every content and account change is recorded."
      />

      <DataTableToolbar
        search={q}
        onSearch={(v) => {
          setQ(v);
          setPage(1);
        }}
        searchPlaceholder="Search audit log…"
      />

      {isLoading ? (
        <LoadingState />
      ) : isError ? (
        <ErrorState message={errMessage(error)} />
      ) : items.length === 0 ? (
        <AdminEmptyState
          title="No activity yet"
          description="Content and account changes will appear here."
        />
      ) : (
        <>
          <AdminTable columns={columns} rows={items} ariaLabel="Audit log" />
          <Pager
            page={data?.page ?? page}
            pageSize={data?.pageSize ?? PAGE_SIZE}
            total={data?.total ?? items.length}
            onPage={setPage}
          />
        </>
      )}
    </div>
  );
}
