/** SCREAMING_SNAKE_CASE backend status/score value -> human words for display.
 * e.g. PARTIALLY_FULFILLED -> "Partially fulfilled". SENT_TO_ERP is the one lifecycle
 * stage with its own name: "Open" — the order was read from the ERP and is awaiting
 * confirmation. Everything else (CONFIRMED, CLOSED, CANCELLED, and the fulfillment/
 * delivery/invoice scores) renders as-is. */
export function statusLabel(value: string): string {
  if (value === "SENT_TO_ERP") return "Open";
  const text = value
    .split("_")
    .map((w) => (w === "ERP" ? "ERP" : w.toLowerCase()))
    .join(" ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
