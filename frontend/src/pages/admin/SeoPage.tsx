import { useEffect, useState } from "react";
import { Button } from "@heroui/react";
import {
  useSettings,
  useUpdateSettings,
  redirectsApi,
  errMessage,
  type AdminSettings,
  type AdminRedirect,
} from "@/lib/admin";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import {
  LoadingState,
  ErrorState,
  AdminEmptyState,
} from "@/components/admin/AdminEmptyState";
import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { ConfirmDialog } from "@/components/admin/ConfirmDialog";
import { EditorModal } from "@/components/admin/EditorModal";
import { LocalizedInput } from "@/components/admin/LocalizedInput";
import { MediaPicker } from "@/components/admin/MediaPicker";
import {
  FormCard,
  TextInput,
  SelectInput,
  SwitchInput,
} from "@/components/admin/FormField";

type SeoDefaults = NonNullable<AdminSettings["seoDefaults"]>;

const EMPTY_REDIRECT: Partial<AdminRedirect> = {
  fromPath: "",
  toPath: "",
  statusCode: 301,
};

export function Component() {
  const { data, isLoading, isError, error } = useSettings();
  const updateSettings = useUpdateSettings();
  const [seo, setSeo] = useState<SeoDefaults>({});

  const redirectsList = redirectsApi.useList({ pageSize: 200 });
  const createRedirect = redirectsApi.useCreate();
  const removeRedirect = redirectsApi.useRemove();
  const [editingRedirect, setEditingRedirect] =
    useState<Partial<AdminRedirect> | null>(null);
  const [toDelete, setToDelete] = useState<AdminRedirect | null>(null);

  useEffect(() => {
    if (data?.seoDefaults) setSeo(data.seoDefaults);
  }, [data]);

  if (isLoading) return <LoadingState />;
  if (isError) return <ErrorState message={errMessage(error)} />;

  const noindex = (seo.robots ?? "").includes("noindex");

  const redirects = redirectsList.data?.items ?? [];
  const redirectColumns: Column<AdminRedirect>[] = [
    { key: "from", header: "From", render: (r) => <code className="text-sm">{r.fromPath}</code> },
    { key: "to", header: "To", render: (r) => <code className="text-sm">{r.toPath}</code> },
    {
      key: "code",
      header: "Code",
      render: (r) => <span className="text-sm text-muted">{r.statusCode}</span>,
    },
    {
      key: "actions",
      header: "",
      align: "end",
      render: (r) => (
        <Button
          variant="tertiary"
          size="sm"
          onPress={() => setToDelete(r)}
          aria-label="Delete redirect"
        >
          Delete
        </Button>
      ),
    },
  ];

  return (
    <div>
      <AdminPageHeader
        title="SEO"
        description="Default metadata and URL redirects."
        actions={
          <Button
            variant="primary"
            size="sm"
            onPress={() => updateSettings.mutate({ seoDefaults: seo })}
            isDisabled={updateSettings.isPending}
          >
            {updateSettings.isPending ? "Saving…" : "Save defaults"}
          </Button>
        }
      />

      <div className="flex flex-col gap-6">
        <FormCard title="Default metadata" description="Applied when a page has no specific SEO.">
          <TextInput
            label="Title pattern"
            value={seo.titlePattern ?? ""}
            onChange={(v) => setSeo((s) => ({ ...s, titlePattern: v }))}
            placeholder="%s — Svaneti with Georgie"
            hint="Use %s as the page-title placeholder."
          />
          <LocalizedInput
            label="Default description"
            multiline
            rows={3}
            value={seo.description}
            onChange={(v) => setSeo((s) => ({ ...s, description: v }))}
          />
          <MediaPicker
            label="Default social share image"
            value={seo.socialImageMediaId}
            onChange={(id) => setSeo((s) => ({ ...s, socialImageMediaId: id }))}
          />
          <TextInput
            label="Canonical base URL"
            value={seo.canonicalBaseUrl ?? ""}
            onChange={(v) => setSeo((s) => ({ ...s, canonicalBaseUrl: v }))}
            placeholder="https://svaneti-with-georgie.com"
          />
          <SwitchInput
            label="Discourage search engines (site-wide noindex)"
            value={noindex}
            onChange={(v) =>
              setSeo((s) => ({ ...s, robots: v ? "noindex,nofollow" : "index,follow" }))
            }
            hint="Individual pages can also set noindex in their own SEO block."
          />
        </FormCard>

        <div>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-display text-lg font-medium text-foreground">Redirects</h2>
            <Button
              variant="outline"
              size="sm"
              onPress={() => setEditingRedirect({ ...EMPTY_REDIRECT })}
            >
              Add redirect
            </Button>
          </div>
          {redirectsList.isLoading ? (
            <LoadingState />
          ) : redirects.length === 0 ? (
            <AdminEmptyState
              title="No redirects"
              description="Add a redirect to forward old URLs to new ones."
              icon="↪"
            />
          ) : (
            <AdminTable columns={redirectColumns} rows={redirects} ariaLabel="Redirects" />
          )}
        </div>
      </div>

      <EditorModal
        isOpen={!!editingRedirect}
        onOpenChange={(open) => !open && setEditingRedirect(null)}
        title="Add redirect"
        size="sm"
        isSaving={createRedirect.isPending}
        onSave={() => {
          if (!editingRedirect) return;
          createRedirect.mutate(editingRedirect, {
            onSuccess: () => setEditingRedirect(null),
          });
        }}
      >
        {editingRedirect && (
          <>
            <TextInput
              label="From path"
              value={editingRedirect.fromPath ?? ""}
              onChange={(v) => setEditingRedirect((r) => (r ? { ...r, fromPath: v } : r))}
              placeholder="/old-tour"
              isRequired
            />
            <TextInput
              label="To path"
              value={editingRedirect.toPath ?? ""}
              onChange={(v) => setEditingRedirect((r) => (r ? { ...r, toPath: v } : r))}
              placeholder="/tours/new-tour"
              isRequired
            />
            <SelectInput
              label="Status code"
              value={String(editingRedirect.statusCode ?? 301)}
              onChange={(v) =>
                setEditingRedirect((r) =>
                  r ? { ...r, statusCode: Number(v) as 301 | 302 } : r,
                )
              }
              options={[
                { value: "301", label: "301 — Permanent" },
                { value: "302", label: "302 — Temporary" },
              ]}
            />
          </>
        )}
      </EditorModal>

      <ConfirmDialog
        isOpen={!!toDelete}
        onOpenChange={(open) => !open && setToDelete(null)}
        title="Delete redirect?"
        body={`${toDelete?.fromPath ?? ""} → ${toDelete?.toPath ?? ""}`}
        destructive
        confirmLabel="Delete"
        isPending={removeRedirect.isPending}
        onConfirm={() =>
          toDelete &&
          removeRedirect.mutate(toDelete.id, { onSuccess: () => setToDelete(null) })
        }
      />
    </div>
  );
}
