import { Chip } from "@heroui/react";
import type { PublishStatus } from "@/lib/types";

type ChipColor = "accent" | "danger" | "default" | "success" | "warning";

const STATUS_COLOR: Record<string, ChipColor> = {
  published: "success",
  draft: "default",
  scheduled: "warning",
  archived: "danger",
  expired: "danger",
};

const STATUS_LABEL: Record<string, string> = {
  published: "Published",
  draft: "Draft",
  scheduled: "Scheduled",
  archived: "Archived",
  expired: "Expired",
};

/** Maps a publish status (or arbitrary state string) to a colored Chip. */
export function StatusChip({ status }: { status: PublishStatus | string | undefined }) {
  const key = status ?? "draft";
  return (
    <Chip variant="soft" size="sm" color={STATUS_COLOR[key] ?? "default"}>
      {STATUS_LABEL[key] ?? key}
    </Chip>
  );
}

/** Simple boolean "published/unpublished" chip for non-envelope resources. */
export function PublishedChip({ published }: { published: boolean | undefined }) {
  return (
    <Chip variant="soft" size="sm" color={published ? "success" : "default"}>
      {published ? "Published" : "Hidden"}
    </Chip>
  );
}

/** Active/inactive chip for banners/popups. */
export function ActiveChip({ active }: { active: boolean | undefined }) {
  return (
    <Chip variant="soft" size="sm" color={active ? "success" : "default"}>
      {active ? "Active" : "Inactive"}
    </Chip>
  );
}
