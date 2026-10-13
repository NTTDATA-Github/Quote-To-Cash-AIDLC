import type { TimelineEntry } from "../api/queries/orders";
import { statusLabel } from "../lib/statusLabel";

// Orders arrive already adopted from the ERP (OrderObserved -> SENT_TO_ERP in
// domain/aggregate.py), so Open is the first real step — the old push-flow states
// (Submitted, Validated, Accepted) never happen for a live order. Fulfilled is a score,
// not a lifecycle step: a closed order must not paint it as a completed step. "RETRYING"
// and "REJECTED"/"CANCELLED" are exceptions overlaid on this sequence, not steps in it.
const LIFECYCLE_STEPS = ["SENT_TO_ERP", "CONFIRMED", "CLOSED"];
const FAILURE_STATUSES = new Set(["REJECTED", "CANCELLED"]);

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

const CheckMark = () => (
  <svg viewBox="0 0 12 12" aria-hidden="true">
    <path d="M2 6.5l2.6 2.6L10 3.2" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const CrossMark = () => (
  <svg viewBox="0 0 12 12" aria-hidden="true">
    <path d="M2.5 2.5l7 7M9.5 2.5l-7 7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);

interface OrderTimelineProps {
  timeline: TimelineEntry[];
  currentStatus: string;
}

/** design/design-system/components/OrderTimeline.md — .erp-timeline/.erp-step from
 * bundle.css. One current step at most; a failure ends the list there rather than
 * drawing steps that will never happen. */
export function OrderTimeline({ timeline, currentStatus }: OrderTimelineProps) {
  const occurredAtByStatus = new Map(timeline.map((t) => [t.status, t.occurredAt]));
  const isRetrying = currentStatus === "RETRYING";
  const isFailed = FAILURE_STATUSES.has(currentStatus);
  const effectiveCurrent = isRetrying ? "SENT_TO_ERP" : currentStatus;
  const currentIndex = LIFECYCLE_STEPS.indexOf(effectiveCurrent);

  if (isFailed) {
    // Show what actually happened (from the real event history), ending at the failure —
    // never invent steps that were never reached.
    return (
      <ol className="erp-timeline">
        {timeline.map((entry, i) => {
          const isLast = i === timeline.length - 1;
          const state = isLast ? "failed" : "done";
          return (
            <li key={`${entry.status}-${entry.occurredAt}`} className={`erp-step erp-step--${state}`}>
              <span className="erp-step__mark">{state === "done" ? <CheckMark /> : <CrossMark />}</span>
              <div>
                <span className="erp-step__label">{statusLabel(entry.status)}</span>
              </div>
              <time className="erp-step__time data">{formatTime(entry.occurredAt)}</time>
            </li>
          );
        })}
      </ol>
    );
  }

  return (
    <ol className="erp-timeline">
      {LIFECYCLE_STEPS.map((step, i) => {
        const done = currentIndex >= 0 && i < currentIndex;
        const isCurrent = step === effectiveCurrent;
        const state = done ? "done" : isCurrent ? "current" : "todo";
        const at = occurredAtByStatus.get(step);
        return (
          <li key={step} className={`erp-step erp-step--${state}`}>
            <span className="erp-step__mark">{state === "done" ? <CheckMark /> : null}</span>
            <div>
              <span className="erp-step__label">{statusLabel(step)}</span>
              {isCurrent && isRetrying && (
                <span className="erp-step__note">Retrying — will be sent again automatically.</span>
              )}
            </div>
            <time className="erp-step__time data">{at ? formatTime(at) : ""}</time>
          </li>
        );
      })}
    </ol>
  );
}
