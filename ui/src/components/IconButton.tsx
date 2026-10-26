import type { LucideIcon } from "lucide-react";

/** An icon-only action with a tooltip and an accessible name. Use it for row actions (edit,
 * remove, pause); keep a text label for the main action on a page. `tone="danger"` is for
 * anything that removes something. */
export function IconButton({
  icon: Icon,
  label,
  tone = "default",
  disabled = false,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  tone?: "default" | "danger";
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={`icon-btn icon-btn--sm${tone === "danger" ? " icon-btn--danger" : ""}`}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={(e) => {
        // Row actions sit inside clickable rows; stop the click selecting the row too.
        e.stopPropagation();
        onClick();
      }}
    >
      <Icon size={16} strokeWidth={1.75} aria-hidden="true" />
    </button>
  );
}
