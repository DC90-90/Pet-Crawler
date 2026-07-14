import type { ReactNode } from "react";
import { Modal, Button } from "@heroui/react";

/** Reusable create/edit modal with a sticky save/cancel footer. */
export function EditorModal({
  isOpen,
  onOpenChange,
  title,
  children,
  onSave,
  isSaving = false,
  saveLabel = "Save",
  size = "lg",
}: {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: ReactNode;
  onSave: () => void;
  isSaving?: boolean;
  saveLabel?: string;
  size?: "sm" | "md" | "lg";
}) {
  return (
    <Modal isOpen={isOpen} onOpenChange={onOpenChange}>
      <Modal.Backdrop variant="blur" isDismissable={!isSaving}>
        <Modal.Container size={size} scroll="inside">
          <Modal.Dialog>
            <Modal.CloseTrigger />
            <Modal.Header>
              <Modal.Heading>{title}</Modal.Heading>
            </Modal.Header>
            <Modal.Body>
              <div className="flex flex-col gap-4">{children}</div>
            </Modal.Body>
            <Modal.Footer>
              <Button
                variant="tertiary"
                onPress={() => onOpenChange(false)}
                isDisabled={isSaving}
              >
                Cancel
              </Button>
              <Button variant="primary" onPress={onSave} isDisabled={isSaving}>
                {isSaving ? "Saving…" : saveLabel}
              </Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
