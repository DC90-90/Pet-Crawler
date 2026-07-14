import { useRef, useState } from "react";
import { Button, Chip, Alert, TextField, Input } from "@heroui/react";
import {
  useMediaList,
  useUploadMedia,
  useRegisterExternalMedia,
  useUpdateMedia,
  useDeleteMedia,
  mediaUrl,
  tx,
  type AdminMedia,
} from "@/lib/admin";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { DataTableToolbar, Pager } from "@/components/admin/DataTableToolbar";
import { EditorModal } from "@/components/admin/EditorModal";
import { ConfirmDialog } from "@/components/admin/ConfirmDialog";
import {
  LoadingState,
  ErrorState,
  AdminEmptyState,
} from "@/components/admin/AdminEmptyState";
import { LocalizedInput } from "@/components/admin/LocalizedInput";
import { TextInput, TagsInput } from "@/components/admin/FormField";
import { MediaImage } from "@/components/primitives";

const PAGE_SIZE = 24;
const KIND_FILTER = [
  { value: "", label: "All media" },
  { value: "image", label: "Images" },
  { value: "video", label: "Videos" },
  { value: "external_video", label: "External video" },
];

function UploadButton() {
  const upload = useUploadMedia();
  const ref = useRef<HTMLInputElement>(null);
  return (
    <>
      <input
        ref={ref}
        type="file"
        accept="image/*,video/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (!file) return;
          const fd = new FormData();
          fd.append("file", file);
          upload.mutate(fd);
          e.target.value = "";
        }}
      />
      <Button
        variant="primary"
        size="sm"
        onPress={() => ref.current?.click()}
        isDisabled={upload.isPending}
      >
        {upload.isPending ? "Uploading…" : "Upload"}
      </Button>
    </>
  );
}

function ExternalForm() {
  const register = useRegisterExternalMedia();
  const [url, setUrl] = useState("");
  return (
    <div className="flex items-end gap-2">
      <div className="min-w-[16rem] flex-1">
        <TextField value={url} onChange={setUrl} className="flex flex-col gap-1">
          <Input placeholder="Paste YouTube / Vimeo URL…" />
        </TextField>
      </div>
      <Button
        variant="outline"
        size="sm"
        isDisabled={!url || register.isPending}
        onPress={() =>
          register.mutate({ url }, { onSuccess: () => setUrl("") })
        }
      >
        Register
      </Button>
    </div>
  );
}

export function Component() {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<AdminMedia | null>(null);
  const [toDelete, setToDelete] = useState<AdminMedia | null>(null);

  const { data, isLoading, isError, error } = useMediaList({
    q,
    kind,
    page,
    pageSize: PAGE_SIZE,
  });
  const updateMedia = useUpdateMedia();
  const deleteMedia = useDeleteMedia();

  const items = data?.items ?? [];
  const setField = <K extends keyof AdminMedia>(k: K, v: AdminMedia[K]) =>
    setEditing((e) => (e ? { ...e, [k]: v } : e));

  const usageCount = toDelete?.usageRefs?.length ?? 0;

  return (
    <div>
      <AdminPageHeader
        title="Media library"
        description="Images and video used across the site."
        actions={
          <div className="flex items-center gap-2">
            <UploadButton />
          </div>
        }
      />

      <div className="mb-4 rounded-xl border border-border bg-surface/40 p-3">
        <p className="mb-2 text-sm font-medium text-foreground">
          Register external video
        </p>
        <ExternalForm />
      </div>

      <DataTableToolbar
        search={q}
        onSearch={(v) => {
          setQ(v);
          setPage(1);
        }}
        searchPlaceholder="Search by filename or tag…"
        filters={[
          {
            label: "Kind",
            value: kind,
            onChange: (v) => {
              setKind(v);
              setPage(1);
            },
            options: KIND_FILTER,
          },
        ]}
      />

      {isLoading ? (
        <LoadingState />
      ) : isError ? (
        <ErrorState message={error instanceof Error ? error.message : "Error"} />
      ) : items.length === 0 ? (
        <AdminEmptyState
          title="No media yet"
          description="Upload an image or register an external video to begin."
          icon="▦"
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {items.map((m) => (
              <button
                key={m.id}
                type="button"
                onClick={() => setEditing(m)}
                className="group overflow-hidden rounded-xl border border-border bg-surface/40 text-start transition hover:border-copper/50"
              >
                <MediaImage
                  url={mediaUrl(m)}
                  alt={tx(m.altText) || m.originalFilename || m.id}
                  ratio="aspect-[4/3]"
                />
                <div className="p-2">
                  <p className="truncate text-xs font-medium text-foreground">
                    {m.originalFilename ?? tx(m.altText) ?? m.id}
                  </p>
                  <div className="mt-1 flex items-center gap-1">
                    <Chip size="sm" variant="soft" color="default">
                      {m.kind}
                    </Chip>
                    {(m.usageRefs?.length ?? 0) > 0 && (
                      <Chip size="sm" variant="soft" color="accent">
                        {m.usageRefs?.length} uses
                      </Chip>
                    )}
                  </div>
                </div>
              </button>
            ))}
          </div>
          <Pager
            page={data?.page ?? page}
            pageSize={data?.pageSize ?? PAGE_SIZE}
            total={data?.total ?? items.length}
            onPage={setPage}
          />
        </>
      )}

      {/* Detail / edit modal */}
      <EditorModal
        isOpen={!!editing}
        onOpenChange={(open) => !open && setEditing(null)}
        title="Media details"
        isSaving={updateMedia.isPending}
        onSave={() => {
          if (!editing) return;
          updateMedia.mutate(
            {
              id: editing.id,
              data: {
                altText: editing.altText,
                caption: editing.caption,
                credit: editing.credit,
                tags: editing.tags,
              },
            },
            { onSuccess: () => setEditing(null) },
          );
        }}
      >
        {editing && (
          <>
            <div className="overflow-hidden rounded-lg border border-border">
              <MediaImage
                url={mediaUrl(editing)}
                alt={tx(editing.altText) || editing.id}
                ratio="aspect-video"
              />
            </div>
            <p className="text-xs text-muted">
              {editing.originalFilename ?? editing.externalUrl ?? editing.id}
              {editing.width && editing.height
                ? ` · ${editing.width}×${editing.height}`
                : ""}
            </p>
            <LocalizedInput
              label="Alt text"
              value={editing.altText}
              onChange={(v) => setField("altText", v)}
              hint="Describe the image for accessibility."
            />
            <LocalizedInput
              label="Caption"
              value={editing.caption}
              onChange={(v) => setField("caption", v)}
            />
            <TextInput
              label="Credit"
              value={editing.credit ?? ""}
              onChange={(v) => setField("credit", v)}
            />
            <TagsInput
              label="Tags"
              value={editing.tags ?? []}
              onChange={(v) => setField("tags", v)}
            />
            {(editing.usageRefs?.length ?? 0) > 0 && (
              <Alert color="warning">
                <Alert.Indicator />
                <Alert.Content>
                  <Alert.Description>
                    Used in {editing.usageRefs?.length} place(s). Deleting may break
                    those references.
                  </Alert.Description>
                </Alert.Content>
              </Alert>
            )}
            <div>
              <Button
                variant="danger"
                size="sm"
                onPress={() => {
                  setToDelete(editing);
                  setEditing(null);
                }}
              >
                Delete media
              </Button>
            </div>
          </>
        )}
      </EditorModal>

      <ConfirmDialog
        isOpen={!!toDelete}
        onOpenChange={(open) => !open && setToDelete(null)}
        title="Delete media?"
        body={
          usageCount > 0
            ? `This media is referenced in ${usageCount} place(s). Deleting it may leave broken references. Continue?`
            : "This media will be permanently deleted."
        }
        destructive
        confirmLabel="Delete"
        isPending={deleteMedia.isPending}
        onConfirm={() =>
          toDelete &&
          deleteMedia.mutate(toDelete.id, { onSuccess: () => setToDelete(null) })
        }
      />
    </div>
  );
}
