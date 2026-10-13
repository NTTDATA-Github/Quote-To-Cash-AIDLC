import { statusRole } from "../components/StatusBadge";
import { statusLabel } from "./statusLabel";

export type Stage = "in-flight" | "completed" | "attention" | "other";

const STAGE_LABEL: Record<Stage, string> = {
  "in-flight": "In flight",
  completed: "Completed",
  attention: "Needs attention",
  other: "Other",
};

/** Buckets a raw order status into the same three groups the dashboard tiles count,
 * so a tile click and the Orders page filter agree on what "in flight" means. */
export function orderStage(rawStatus: string): Stage {
  const role = statusRole(statusLabel(rawStatus));
  if (role === "progress") return "in-flight";
  if (role === "success") return "completed";
  if (role === "danger" || role === "warning") return "attention";
  return "other";
}

export function stageLabel(stage: Stage): string {
  return STAGE_LABEL[stage];
}

// src/modules/sales/ordering/domain/models.py — OrderState, in lifecycle order, with the
// three exception states (reached from anywhere) sorted after. Used only to make a
// Status column sort meaningfully instead of alphabetically ("Closed" would otherwise
// sort before "Confirmed").
const STATE_RANK: Record<string, number> = {
  SUBMITTED: 0,
  VALIDATED: 1,
  ACCEPTED: 2,
  SENT_TO_ERP: 3,
  CONFIRMED: 4,
  CLOSED: 5,
  RETRYING: 6,
  REJECTED: 7,
  CANCELLED: 8,
};

export function statusRank(rawStatus: string): number {
  return STATE_RANK[rawStatus] ?? 99;
}
