import { useState } from "react";
import {
  AlertTriangle,
  Bell,
  Building2,
  LayoutDashboard,
  Plug,
  ShoppingCart,
  Users,
  Workflow,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Modal } from "./Modal";

export const TOUR_DISMISSED_KEY = "adminops.tourDismissed";

type Step = { icon: LucideIcon; title: string; body: string };

// Copy here is each page's own PageHeader subtitle, in the order an operator actually
// needs it: set up where orders come from before looking at the orders themselves.
const STEPS: Step[] = [
  {
    icon: Plug,
    title: "1. ERP connections",
    body: "Start here. Register each ERP instance you pull orders from or push them to — credentials are stored encrypted and never shown again after saving. A connection works immediately if its ERP already has an adapter (Odoo, NetSuite); otherwise it's saved but won't deliver anything until it's mapped.",
  },
  {
    icon: Workflow,
    title: "2. ERP mapping",
    body: "For a connection with no adapter yet: connect it, match its fields to ours, review the proposed mapping, then approve it to generate the adapter. A connection only shows up here while its ERP type genuinely needs this — already-mapped or in-progress ones are filtered out on purpose.",
  },
  {
    icon: Building2,
    title: "3. Subsidiaries",
    body: "Each row is one distributor company. Once its ERP connection exists, route the subsidiary to it here — this is what decides which ERP a reseller's order actually lands in.",
  },
  {
    icon: Users,
    title: "4. Resellers",
    body: "Each reseller has a customer link into every ERP connection it buys from. This is where you manage that roster and the bindings behind it.",
  },
  {
    icon: ShoppingCart,
    title: "5. Orders",
    body: "Every order across every reseller, once connections and routing are set up. Open one to see its full lifecycle: fulfillment, delivery, and invoice status.",
  },
  {
    icon: Bell,
    title: "6. Notifications",
    body: "Every status update sent to a reseller, across every reseller. Open a row to jump straight to the order it's about.",
  },
  {
    icon: AlertTriangle,
    title: "7. Failed messages",
    body: "Orders that could not be delivered to an ERP, or were cancelled. Most retrying ones resolve on their own — this is where to look when one doesn't.",
  },
  {
    icon: LayoutDashboard,
    title: "8. Dashboard",
    body: "The at-a-glance view once everything above is set up — come back here day to day.",
  },
];

function markDismissed() {
  try {
    localStorage.setItem(TOUR_DISMISSED_KEY, "1");
  } catch {
    // best-effort only — a private window or blocked storage just means we ask again
  }
}

export function ProductTour({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [step, setStep] = useState<number | null>(null); // null = the initial yes/no prompt

  function close() {
    markDismissed();
    setStep(null);
    onClose();
  }

  if (step === null) {
    return (
      <Modal open={open} onClose={close} title="Welcome — want a quick tour?" width={440}>
        <p className="tour__prompt">
          It walks through everything an operator sets up here, in the order you'd actually do
          it: ERP connections first, then mapping, routing, and where orders end up. Takes about
          a minute.
        </p>
        <div className="modal__foot" style={{ padding: 0, border: "none", marginTop: "var(--space-5)" }}>
          <button type="button" className="erp-btn erp-btn--ghost" onClick={close}>
            Skip
          </button>
          <button type="button" className="erp-btn erp-btn--primary" onClick={() => setStep(0)}>
            Show me around
          </button>
        </div>
      </Modal>
    );
  }

  const current = STEPS[step];
  const isLast = step === STEPS.length - 1;

  return (
    <Modal open={open} onClose={close} title={current.title} width={520}>
      <div className="tour__step">
        <div className="tour__icon">
          <current.icon size={22} strokeWidth={1.75} />
        </div>
        <p>{current.body}</p>
      </div>
      <ol className="wizard-steps tour__dots">
        {STEPS.map((_, i) => (
          <li key={i} className={i === step ? "is-active" : i < step ? "is-done" : ""}>
            <span className="wizard-steps__dot">{i < step ? "✓" : i + 1}</span>
          </li>
        ))}
      </ol>
      <div className="modal__foot" style={{ padding: 0, border: "none", marginTop: "var(--space-4)" }}>
        <button type="button" className="erp-btn erp-btn--ghost" onClick={close}>
          Skip
        </button>
        <div style={{ flex: 1 }} />
        {step > 0 && (
          <button type="button" className="erp-btn erp-btn--secondary" onClick={() => setStep(step - 1)}>
            Back
          </button>
        )}
        <button
          type="button"
          className="erp-btn erp-btn--primary"
          onClick={() => (isLast ? close() : setStep(step + 1))}
        >
          {isLast ? "Done" : "Next"}
        </button>
      </div>
    </Modal>
  );
}
