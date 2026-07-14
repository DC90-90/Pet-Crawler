import { useMemo, useState, useRef } from "react";
import { Modal, Button, SearchField, Input, Spinner, Chip } from "@heroui/react";
import {
  useMediaList,
  useUploadMedia,
  mediaUrl,
  type AdminMedia,
} from "@/lib/admin";
import { MediaImage } from "@/components/primitives";

function useMediaIndex() {
  const { data } = useMediaList({ pageSize: 200 });
  const items = useMemo(() => data?.items ?? [], [data]);
  const byId = useMemo(() => {
    const m = new Map<string, AdminMedia>();
    items.forEach((it) => m.set(it.id, it));
    return m;
  }, [items]);
  return { items, byId };
}

function MediaGrid({
  onPick,
  selectedIds,
}: {
  onPick: (m: AdminMedia) => void;
  selectedIds: string[];
}) {
  const [q, setQ] = useState("");
  const { data, isLoading } = useMediaList({ q, pageSize: 60 });
  const items = data?.items ?? [];

  return (
    <div className="flex flex-col gap-3">
      <SearchField value={q} onChange={setQ} aria-label="Search media">
        <Input placeholder="Search media by name or tag…" />
      </SearchField>
      {isLoading ? (
        <div className="grid place-items-center py-10">
          <Spinner />
        </div>
      ) : items.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted">No media found.</p>
      ) : (
        <div className="grid max-h-[50vh] grid-cols-3 gap-2 overflow-y-auto sm:grid-cols-4">
          {items.map((m) => {
            const selected = selectedIds.includes(m.id);
            return (
              <button
                key={m.id}
                type="button"
                onClick={() => onPick(m)}
                className={`group relative overflow-hidden rounded-lg border-2 text-start transition ${
                  selected ? "border-copper" : "border-transparent hover:border-border"
                }`}
                aria-pressed={selected}
              >
                <MediaImage
                  url={mediaUrl(m)}
                  alt={m.originalFilename ?? m.id}
                  ratio="aspect-square"
                />
                {selected && (
                  <span className="absolute end-1 top-1">
                    <Chip size="sm" variant="primary" color="accent">
                      ✓
                    </Chip>
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function UploadRow() {
  const upload = useUploadMedia();
  const fileRef = useRef<HTMLInputElement>(null);
  return (
    <div className="flex items-center gap-2 border-t border-border pt-3">
      <input
        ref={fileRef}
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
        variant="outline"
        size="sm"
        onPress={() => fileRef.current?.click()}
        isDisabled={upload.isPending}
      >
        {upload.isPending ? "Uploading…" : "Upload new"}
      </Button>
      <span className="text-xs text-muted">Newly uploaded media appears in the grid.</span>
    </div>
  );
}

/** Single-media picker returning a media id. */
export function MediaPicker({
  label,
  value,
  onChange,
  hint,
}: {
  label: string;
  value: string | undefined;
  onChange: (id: string | undefined) => void;
  hint?: string;
}) {
  const [open, setOpen] = useState(false);
  const { byId } = useMediaIndex();
  const selected = value ? byId.get(value) : undefined;

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-sm font-medium text-foreground">{label}</span>
      <div className="flex items-center gap-3">
        <div className="h-20 w-28 shrink-0 overflow-hidden rounded-lg border border-border">
          <MediaImage
            url={selected ? mediaUrl(selected) : undefined}
            alt={label}
            ratio="aspect-[7/5]"
          />
        </div>
        <div className="flex flex-col gap-1">
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onPress={() => setOpen(true)}>
              {value ? "Change" : "Choose media"}
            </Button>
            {value && (
              <Button
                variant="tertiary"
                size="sm"
                onPress={() => onChange(undefined)}
              >
                Remove
              </Button>
            )}
          </div>
          {hint && <span className="text-xs text-muted">{hint}</span>}
        </div>
      </div>

      <Modal isOpen={open} onOpenChange={setOpen}>
        <Modal.Backdrop variant="blur">
          <Modal.Container size="lg">
            <Modal.Dialog>
              <Modal.CloseTrigger />
              <Modal.Header>
                <Modal.Heading>Select media</Modal.Heading>
              </Modal.Header>
              <Modal.Body>
                <MediaGrid
                  selectedIds={value ? [value] : []}
                  onPick={(m) => {
                    onChange(m.id);
                    setOpen(false);
                  }}
                />
                <UploadRow />
              </Modal.Body>
            </Modal.Dialog>
          </Modal.Container>
        </Modal.Backdrop>
      </Modal>
    </div>
  );
}

/** Multi-media picker returning an ordered array of media ids. */
export function MediaMultiPicker({
  label,
  value,
  onChange,
  hint,
}: {
  label: string;
  value: string[];
  onChange: (ids: string[]) => void;
  hint?: string;
}) {
  const [open, setOpen] = useState(false);
  const { byId } = useMediaIndex();

  const toggle = (id: string) =>
    onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id]);

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-foreground">{label}</span>
        <Button variant="outline" size="sm" onPress={() => setOpen(true)}>
          Manage ({value.length})
        </Button>
      </div>
      {hint && <span className="text-xs text-muted">{hint}</span>}
      {value.length > 0 && (
        <div className="grid grid-cols-4 gap-2 sm:grid-cols-6">
          {value.map((id) => (
            <div key={id} className="relative overflow-hidden rounded-lg border border-border">
              <MediaImage url={mediaUrl(byId.get(id))} alt={id} ratio="aspect-square" />
              <button
                type="button"
                aria-label="Remove image"
                onClick={() => toggle(id)}
                className="absolute end-0.5 top-0.5 rounded-full bg-background/80 px-1.5 text-xs"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}

      <Modal isOpen={open} onOpenChange={setOpen}>
        <Modal.Backdrop variant="blur">
          <Modal.Container size="lg">
            <Modal.Dialog>
              <Modal.CloseTrigger />
              <Modal.Header>
                <Modal.Heading>Select images ({value.length})</Modal.Heading>
              </Modal.Header>
              <Modal.Body>
                <MediaGrid selectedIds={value} onPick={(m) => toggle(m.id)} />
                <UploadRow />
              </Modal.Body>
              <Modal.Footer>
                <Button variant="primary" onPress={() => setOpen(false)}>
                  Done
                </Button>
              </Modal.Footer>
            </Modal.Dialog>
          </Modal.Container>
        </Modal.Backdrop>
      </Modal>
    </div>
  );
}
