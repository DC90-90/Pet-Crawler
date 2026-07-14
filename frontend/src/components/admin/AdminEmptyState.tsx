import type { ReactNode } from "react";
import { EmptyState, Spinner, Alert } from "@heroui/react";

/** Friendly empty placeholder with optional action. */
export function AdminEmptyState({
  title,
  description,
  action,
  icon = "🏔️",
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <EmptyState className="grid place-items-center gap-3 rounded-2xl border border-dashed border-border bg-surface/40 px-6 py-16 text-center">
      <div className="text-4xl" aria-hidden>
        {icon}
      </div>
      <div>
        <p className="font-display text-lg font-medium text-foreground">{title}</p>
        {description && (
          <p className="mx-auto mt-1 max-w-md text-sm text-muted">{description}</p>
        )}
      </div>
      {action && <div className="mt-2">{action}</div>}
    </EmptyState>
  );
}

/** Centered spinner for loading states. */
export function LoadingState({ label }: { label?: string }) {
  return (
    <div className="grid min-h-[40vh] place-items-center gap-3">
      <Spinner />
      {label && <p className="text-sm text-muted">{label}</p>}
    </div>
  );
}

/** Inline error surface. */
export function ErrorState({ message }: { message: string }) {
  return (
    <Alert color="danger">
      <Alert.Indicator />
      <Alert.Content>
        <Alert.Title>Something went wrong</Alert.Title>
        <Alert.Description>{message}</Alert.Description>
      </Alert.Content>
    </Alert>
  );
}
