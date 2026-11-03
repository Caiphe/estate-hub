"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";

type ConfirmDialogProps = {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  pending?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

/**
 * A modal confirmation built on the native <dialog>: showModal() traps focus and makes the
 * rest of the page inert, Escape cancels, and focus returns to the trigger on close. The
 * cancel button gets initial focus so Enter never confirms a destructive action by
 * accident.
 */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  pending = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const bodyId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
      cancelRef.current?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      className="dialog"
      aria-labelledby={titleId}
      aria-describedby={bodyId}
      onCancel={(event) => {
        event.preventDefault();
        if (!pending) onCancel();
      }}
    >
      <h2 id={titleId} className="dialog-title">
        {title}
      </h2>
      <div id={bodyId}>{children}</div>
      <div className="dialog-actions">
        <button
          ref={cancelRef}
          type="button"
          className="button button-secondary"
          onClick={onCancel}
          disabled={pending}
        >
          Cancel
        </button>
        <button type="button" className="button button-danger" onClick={onConfirm} disabled={pending}>
          {pending ? "Working…" : confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
