import type { ReactNode } from "react";
import { Modal, Button } from "@heroui/react";

/**
 * Controlled confirm dialog built on HeroUI Modal.
 * `isOpen`/`onOpenChange` sit on the Modal root; `isDismissable` on the Backdrop.
 */
export function ConfirmDialog({
  isOpen,
  onOpenChange,
  title,
  body,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  destructive = false,
  isPending = false,
  onConfirm,
}: {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  body?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  isPending?: boolean;
  onConfirm: () => void;
}) {
  return (
    <Modal isOpen={isOpen} onOpenChange={onOpenChange}>
      <Modal.Backdrop variant="blur" isDismissable={!isPending}>
        <Modal.Container size="sm">
          <Modal.Dialog>
            <Modal.CloseTrigger />
            <Modal.Header>
              <Modal.Heading>{title}</Modal.Heading>
            </Modal.Header>
            <Modal.Body>
              {typeof body === "string" ? (
                <p className="text-sm text-muted">{body}</p>
              ) : (
                body
              )}
            </Modal.Body>
            <Modal.Footer>
              <Button
                variant="tertiary"
                onPress={() => onOpenChange(false)}
                isDisabled={isPending}
              >
                {cancelLabel}
              </Button>
              <Button
                variant={destructive ? "danger" : "primary"}
                onPress={onConfirm}
                isDisabled={isPending}
              >
                {isPending ? "Working…" : confirmLabel}
              </Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
