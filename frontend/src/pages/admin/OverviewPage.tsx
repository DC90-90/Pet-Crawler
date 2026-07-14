import { Link, useNavigate } from "react-router-dom";
import { Card, Button, Chip } from "@heroui/react";
import { useOverview, useAuditLogs } from "@/lib/admin";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { LoadingState, ErrorState } from "@/components/admin/AdminEmptyState";
import { errMessage } from "@/lib/admin";

function StatCard({
  label,
  value,
  accent,
  to,
}: {
  label: string;
  value: number;
  accent?: boolean;
  to?: string;
}) {
  const body = (
    <Card
      className={`h-full border p-4 transition hover:border-copper/50 ${
        accent ? "border-copper/40 bg-copper/5" : "border-border bg-surface/50"
      }`}
    >
      <Card.Content className="p-0">
        <p className="text-sm text-muted">{label}</p>
        <p className="mt-1 font-display text-3xl font-semibold text-foreground">
          {value}
        </p>
      </Card.Content>
    </Card>
  );
  return to ? (
    <Link to={to} className="block">
      {body}
    </Link>
  ) : (
    body
  );
}

const ACTION_COLORS: Record<string, "success" | "warning" | "danger" | "accent" | "default"> = {
  create: "accent",
  edit: "default",
  publish: "success",
  unpublish: "warning",
  delete: "danger",
  archive: "warning",
};

export function Component() {
  const navigate = useNavigate();
  const { data, isLoading, isError, error } = useOverview();
  const audit = useAuditLogs({ pageSize: 8 });

  if (isLoading) return <LoadingState />;
  if (isError) return <ErrorState message={errMessage(error)} />;

  const o = data ?? {};
  const recent = data?.recentActivity ?? audit.data?.items ?? [];

  return (
    <div>
      <AdminPageHeader
        title="Dashboard"
        description="A calm overview of what needs attention today."
        actions={
          <>
            <Button variant="primary" size="sm" onPress={() => navigate("/admin/tours/new")}>
              New tour
            </Button>
            <Button variant="outline" size="sm" onPress={() => navigate("/admin/articles")}>
              New article
            </Button>
          </>
        }
      />

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <StatCard
          label="Published tours"
          value={o.tours?.published ?? 0}
          accent
          to="/admin/tours"
        />
        <StatCard label="Draft tours" value={o.tours?.draft ?? 0} to="/admin/tours" />
        <StatCard
          label="Active offers"
          value={o.offers?.active ?? 0}
          to="/admin/offers"
        />
        <StatCard
          label="Scheduled offers"
          value={o.offers?.scheduled ?? 0}
          to="/admin/offers"
        />
        <StatCard
          label="Active popups"
          value={o.popups?.active ?? 0}
          to="/admin/popups"
        />
        <StatCard
          label="New inquiries"
          value={o.inquiries?.new ?? 0}
          accent
          to="/admin/inquiries"
        />
        <StatCard
          label="Recent uploads"
          value={o.media?.recent ?? 0}
          to="/admin/media"
        />
        <StatCard
          label="Needs verification"
          value={o.needsVerification ?? 0}
        />
      </section>

      <section className="mt-8 grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <h2 className="mb-3 font-display text-lg font-medium text-foreground">
            Recent activity
          </h2>
          <Card className="border border-border bg-surface/40">
            <Card.Content className="divide-y divide-border p-0">
              {recent.length === 0 ? (
                <p className="p-4 text-sm text-muted">No recent activity.</p>
              ) : (
                recent.map((log) => (
                  <div key={log.id} className="flex items-center gap-3 p-3">
                    <Chip
                      size="sm"
                      variant="soft"
                      color={ACTION_COLORS[log.action] ?? "default"}
                    >
                      {log.action}
                    </Chip>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm text-foreground">
                        {log.summary ?? `${log.action} ${log.entity ?? ""}`}
                      </p>
                      <p className="text-xs text-muted">
                        {log.userEmail ?? "system"}
                        {log.at ? ` · ${new Date(log.at).toLocaleString()}` : ""}
                      </p>
                    </div>
                  </div>
                ))
              )}
            </Card.Content>
          </Card>
        </div>

        <div>
          <h2 className="mb-3 font-display text-lg font-medium text-foreground">
            Quick create
          </h2>
          <div className="flex flex-col gap-2">
            <Button variant="outline" fullWidth onPress={() => navigate("/admin/tours/new")}>
              ⛰ New tour
            </Button>
            <Button variant="outline" fullWidth onPress={() => navigate("/admin/destinations")}>
              📍 New destination
            </Button>
            <Button variant="outline" fullWidth onPress={() => navigate("/admin/offers")}>
              ％ New offer
            </Button>
            <Button variant="outline" fullWidth onPress={() => navigate("/admin/media")}>
              ▦ Upload media
            </Button>
            <Button variant="outline" fullWidth onPress={() => navigate("/admin/inquiries")}>
              ✉ Review inquiries
            </Button>
          </div>
        </div>
      </section>
    </div>
  );
}
