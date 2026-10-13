import { createPortal } from "react-dom";
import { useOutletContext } from "react-router-dom";
import type { ReactNode } from "react";

export type HeaderSlot = HTMLDivElement | null;

/** Every routed page renders one of these instead of its own `<h1>` — the header bar
 * is the single place a page's name is shown (AppShell owns the slot; see its
 * `<div className="top-title" ref={setHeaderSlot} />`). Portaling avoids lifting title
 * state through context/effects, which — since `actions`/`subtitle` are fresh JSX every
 * render — would re-trigger on every render and fight React's render cycle. */
export function PageHeader({
  eyebrow,
  title,
  subtitle,
  actions,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  const slot = useOutletContext<HeaderSlot>();
  if (!slot) return null;
  return createPortal(
    <>
      <div className="top-title__text">
        {eyebrow && <div className="top-title__eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="top-title__actions">{actions}</div>}
    </>,
    slot,
  );
}
