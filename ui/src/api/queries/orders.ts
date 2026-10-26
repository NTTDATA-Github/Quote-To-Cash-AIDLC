export interface Money {
  // string, not number: the server sends Decimal-exact money as a string (fixed
  // 2026-10-04 — float couldn't represent e.g. 19.99 exactly). Parse with Number()
  // only for display formatting, never for further arithmetic.
  amount: string;
  currency: string;
}

export interface TimelineEntry {
  status: string;
  occurredAt: string;
}
