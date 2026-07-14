import { useEffect, useState } from "react";
import { Alert } from "@heroui/react";
import {
  subscribeToasts,
  dismissToast,
  type ToastMessage,
} from "@/lib/admin";

const KIND_MAP: Record<ToastMessage["kind"], "success" | "danger" | "warning"> = {
  success: "success",
  danger: "danger",
  warning: "warning",
};

/** Global toast host. Mount once inside AdminLayout. */
export function Toaster() {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  useEffect(() => subscribeToasts(setToasts), []);

  if (toasts.length === 0) return null;

  return (
    <div
      className="pointer-events-none fixed bottom-4 end-4 z-[100] flex w-[min(92vw,22rem)] flex-col gap-2"
      role="region"
      aria-label="Notifications"
    >
      {toasts.map((t) => (
        <div key={t.id} className="pointer-events-auto animate-in">
          <Alert color={KIND_MAP[t.kind]}>
            <Alert.Indicator />
            <Alert.Content>
              <Alert.Description>{t.message}</Alert.Description>
            </Alert.Content>
            <button
              type="button"
              aria-label="Dismiss notification"
              className="ms-auto rounded-md px-1 text-sm opacity-70 hover:opacity-100 focus-visible:outline-2"
              onClick={() => dismissToast(t.id)}
            >
              ✕
            </button>
          </Alert>
        </div>
      ))}
    </div>
  );
}
