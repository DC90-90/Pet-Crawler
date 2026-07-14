import { useState } from "react";
import { Button, Chip, Drawer, Separator } from "@heroui/react";
import {
  useInquiries,
  useUpdateInquiry,
  useMe,
  inquiriesExportUrl,
  errMessage,
  type Inquiry,
} from "@/lib/admin";
import { apiBase } from "@/lib/api";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { DataTableToolbar, Pager } from "@/components/admin/DataTableToolbar";
import {
  LoadingState,
  ErrorState,
  AdminEmptyState,
} from "@/components/admin/AdminEmptyState";
import { SelectInput, TextAreaInput } from "@/components/admin/FormField";
import { INQUIRY_STATUS_OPTIONS, INQUIRY_STATUS_FILTER } from "@/components/admin/constants";

const PAGE_SIZE = 20;

const STATUS_COLOR: Record<string, "accent" | "success" | "warning" | "danger" | "default"> = {
  new: "accent",
  reviewing: "warning",
  contacted: "warning",
  quoted: "warning",
  confirmed: "success",
  completed: "success",
  closed: "default",
  spam: "danger",
};

function Detail({ label, value }: { label: string; value?: string | number | null }) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <div className="flex justify-between gap-4 py-1 text-sm">
      <span className="text-muted">{label}</span>
      <span className="text-end font-medium text-foreground">{value}</span>
    </div>
  );
}

export function Component() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Inquiry | null>(null);
  const [note, setNote] = useState("");

  const { data: me } = useMe();
  const { data, isLoading, isError, error } = useInquiries({
    q,
    status,
    page,
    pageSize: PAGE_SIZE,
  });
  const update = useUpdateInquiry();

  const items = data?.items ?? [];

  const changeStatus = (inq: Inquiry, next: string) =>
    update.mutate(
      { id: inq.id, data: { status: next as Inquiry["status"] } },
      { onSuccess: () => setSelected((s) => (s ? { ...s, status: next as Inquiry["status"] } : s)) },
    );

  const addNote = (inq: Inquiry) => {
    if (!note.trim()) return;
    const notes = [
      ...(inq.notes ?? []),
      { authorId: me?.id ?? "", text: note.trim(), at: new Date().toISOString() },
    ];
    update.mutate(
      { id: inq.id, data: { notes } },
      {
        onSuccess: () => {
          setSelected((s) => (s ? { ...s, notes } : s));
          setNote("");
        },
      },
    );
  };

  const columns: Column<Inquiry>[] = [
    {
      key: "name",
      header: "Name",
      render: (i) => (
        <button
          type="button"
          onClick={() => setSelected(i)}
          className="flex flex-col items-start text-start hover:text-copper"
        >
          <span className="font-medium text-foreground">{i.fullName}</span>
          <span className="text-xs text-muted">{i.email}</span>
        </button>
      ),
    },
    {
      key: "status",
      header: "Status",
      render: (i) => (
        <Chip size="sm" variant="soft" color={STATUS_COLOR[i.status] ?? "default"}>
          {i.status}
        </Chip>
      ),
    },
    {
      key: "group",
      header: "Group",
      render: (i) => (
        <span className="text-sm text-muted">{i.groupSize ? `${i.groupSize} pax` : "—"}</span>
      ),
    },
    {
      key: "created",
      header: "Received",
      render: (i) => (
        <span className="text-sm text-muted">
          {i.createdAt ? new Date(i.createdAt).toLocaleDateString() : "—"}
        </span>
      ),
    },
  ];

  return (
    <div>
      <AdminPageHeader
        title="Inquiries"
        description="Trip requests from the public site."
        actions={
          <a href={`${apiBase}${inquiriesExportUrl}`} download>
            <Button variant="outline" size="sm">
              Export CSV
            </Button>
          </a>
        }
      />

      <DataTableToolbar
        search={q}
        onSearch={(v) => {
          setQ(v);
          setPage(1);
        }}
        searchPlaceholder="Search by name, email…"
        filters={[
          {
            label: "Status",
            value: status,
            onChange: (v) => {
              setStatus(v);
              setPage(1);
            },
            options: INQUIRY_STATUS_FILTER,
          },
        ]}
      />

      {isLoading ? (
        <LoadingState />
      ) : isError ? (
        <ErrorState message={errMessage(error)} />
      ) : items.length === 0 ? (
        <AdminEmptyState title="No inquiries" icon="✉" />
      ) : (
        <>
          <AdminTable columns={columns} rows={items} ariaLabel="Inquiries" />
          <Pager
            page={data?.page ?? page}
            pageSize={data?.pageSize ?? PAGE_SIZE}
            total={data?.total ?? items.length}
            onPage={setPage}
          />
        </>
      )}

      <Drawer isOpen={!!selected} onOpenChange={(open) => !open && setSelected(null)}>
        <Drawer.Backdrop variant="blur">
          <Drawer.Content placement="right">
            <Drawer.Dialog className="w-[min(92vw,30rem)]">
              <Drawer.CloseTrigger />
              <Drawer.Header>
                <Drawer.Heading>{selected?.fullName}</Drawer.Heading>
              </Drawer.Header>
              <Drawer.Body>
                {selected && (
                  <div className="flex flex-col gap-4">
                    <div className="flex flex-wrap gap-2">
                      {selected.phone && (
                        <a
                          href={`https://wa.me/${selected.phone.replace(/[^0-9]/g, "")}`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <Button variant="secondary" size="sm">
                            WhatsApp
                          </Button>
                        </a>
                      )}
                      <a href={`mailto:${selected.email}`}>
                        <Button variant="outline" size="sm">
                          Email
                        </Button>
                      </a>
                    </div>

                    <SelectInput
                      label="Status"
                      value={selected.status}
                      onChange={(v) => changeStatus(selected, v)}
                      options={INQUIRY_STATUS_OPTIONS}
                    />

                    <section className="rounded-lg border border-border p-3">
                      <Detail label="Email" value={selected.email} />
                      <Detail label="Phone" value={selected.phone} />
                      <Detail label="Country" value={selected.country} />
                      <Detail label="Language" value={selected.preferredLanguage} />
                      <Detail label="Arrival" value={selected.arrivalDate} />
                      <Detail label="Departure" value={selected.departureDate} />
                      <Detail
                        label="Flexible dates"
                        value={selected.flexibleDates ? "Yes" : undefined}
                      />
                      <Detail label="Group size" value={selected.groupSize} />
                      <Detail label="Children" value={selected.children} />
                      <Detail label="Activity level" value={selected.activityLevel} />
                      <Detail
                        label="Transport"
                        value={selected.needTransport ? "Needed" : undefined}
                      />
                      <Detail label="Pickup" value={selected.pickupLocation} />
                      <Detail label="Accommodation" value={selected.accommodationStatus} />
                      <Detail
                        label="Interests"
                        value={selected.interests?.join(", ")}
                      />
                    </section>

                    <div>
                      <p className="mb-1 text-sm font-medium text-foreground">Message</p>
                      <p className="rounded-lg border border-border bg-surface/40 p-3 text-sm text-muted">
                        {selected.message}
                      </p>
                    </div>

                    <Separator />

                    <div>
                      <p className="mb-2 text-sm font-medium text-foreground">Notes</p>
                      <div className="flex flex-col gap-2">
                        {(selected.notes ?? []).map((n, i) => (
                          <div
                            key={i}
                            className="rounded-lg border border-border bg-surface/40 p-2 text-sm"
                          >
                            <p className="text-foreground">{n.text}</p>
                            <p className="text-xs text-muted">
                              {n.at ? new Date(n.at).toLocaleString() : ""}
                            </p>
                          </div>
                        ))}
                        {(selected.notes?.length ?? 0) === 0 && (
                          <p className="text-xs text-muted">No notes yet.</p>
                        )}
                      </div>
                      <div className="mt-2 flex flex-col gap-2">
                        <TextAreaInput
                          label="Add a note"
                          value={note}
                          onChange={setNote}
                          rows={2}
                        />
                        <Button
                          variant="primary"
                          size="sm"
                          isDisabled={update.isPending || !note.trim()}
                          onPress={() => addNote(selected)}
                        >
                          Add note
                        </Button>
                      </div>
                    </div>

                    {(selected.timeline?.length ?? 0) > 0 && (
                      <>
                        <Separator />
                        <div>
                          <p className="mb-2 text-sm font-medium text-foreground">Timeline</p>
                          <ol className="flex flex-col gap-2 border-s border-border ps-3">
                            {selected.timeline?.map((t, i) => (
                              <li key={i} className="text-sm">
                                <p className="text-foreground">{t.summary ?? t.type}</p>
                                <p className="text-xs text-muted">
                                  {t.at ? new Date(t.at).toLocaleString() : ""}
                                </p>
                              </li>
                            ))}
                          </ol>
                        </div>
                      </>
                    )}
                  </div>
                )}
              </Drawer.Body>
            </Drawer.Dialog>
          </Drawer.Content>
        </Drawer.Backdrop>
      </Drawer>
    </div>
  );
}
