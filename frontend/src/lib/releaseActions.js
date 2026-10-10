import { useRelease } from "@/contexts/ReleaseContext";

export const READ_ONLY_REASON = "Disabled in read-only mode; no changes will be submitted.";
export const ADMIN_READ_ONLY_REASON = "Administrative changes require an approved maintenance operation.";

export function useReleaseActions() {
  const release = useRelease();
  const enabled = (capability) => release?.mode === "active" && release?.capabilities?.[capability] === true;
  return { canEdit: enabled("manual_edits"), canRefresh: enabled("manual_refresh"),
    canSchedule: enabled("automatic_refresh"), canDeliver: enabled("email"), canDigest: enabled("digests") };
}