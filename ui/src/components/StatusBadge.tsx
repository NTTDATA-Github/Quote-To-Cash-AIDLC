export type Role = "neutral" | "progress" | "success" | "warning" | "danger";

// design/README.md "Status badge roles" — the exact, closed vocabulary this app uses.
// Order/fulfillment/delivery/invoice statuses come from the backend as raw
// SCREAMING_SNAKE_CASE; callers pass them through lib/statusLabel.ts first, so this table
// is keyed on the resulting Title Case text. Connection/binding statuses (ConnectionStatus,
// BindingStatus) come through as raw enum values with no translation — both forms are
// mapped here.
const ROLE_BY_STATUS: Record<string, Role> = {
  Draft: "neutral",
  Paused: "neutral",
  PAUSED: "neutral",
  Open: "progress",
  Confirmed: "progress",
  Onboarding: "progress",
  Closed: "success",
  Fulfilled: "success",
  Delivered: "success",
  Active: "success",
  ACTIVE: "success",
  Verified: "success",
  VERIFIED: "success",
  Retrying: "warning",
  "To verify": "warning",
  TO_VERIFY: "warning",
  "Needs owner": "warning",
  Slow: "warning",
  Rejected: "danger",
  Failed: "danger",
  Unreachable: "danger",
  "Dead-lettered": "danger",
  Cancelled: "danger",
  CANCELLED: "danger",
  REMOVED: "danger",
};

function roleFor(status: string): Role {
  return ROLE_BY_STATUS[status] ?? "neutral";
}

/** The design-system badge role for a status, exported so dashboards can classify and
 * colour-group statuses with the same vocabulary the badge uses. Accepts either a Title
 * Case label (from lib/statusLabel) or a raw enum value — both are in ROLE_BY_STATUS. */
export function statusRole(status: string): Role {
  return roleFor(status);
}

/** design/design-system/components/StatusBadge.md — word + glyph, never color alone. */
export function StatusBadge({ status }: { status: string }) {
  return <span className={`erp-badge erp-badge--${roleFor(status)}`}>{status}</span>;
}
