import { useEffect, type ReactNode } from "react";
import { X } from "lucide-react";

/** A side panel over the current page — for "see more about this one thing" without
 * losing the list behind it (Linear/Trello card-click pattern). Esc and the backdrop
 * both close it; the backdrop also stops the page behind it from scrolling. */
export function Drawer({
  open,
  onClose,
  title,
  actions,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="drawer-layer">
      <div className="drawer-backdrop" onClick={onClose} aria-hidden="true" />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined}>
        <header className="drawer__head">
          <div className="drawer__title">{title}</div>
          <div className="drawer__headright">
            {actions}
            <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>
              <X size={16} strokeWidth={2} />
            </button>
          </div>
        </header>
        <div className="drawer__body">{children}</div>
      </aside>
    </div>
  );
}
