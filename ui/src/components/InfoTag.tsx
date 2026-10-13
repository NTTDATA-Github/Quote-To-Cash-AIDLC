import { useState, type FocusEvent, type MouseEvent } from "react";

/** Hover hint. Positioned against the viewport so a table's overflow does not clip it. */
export function InfoTag({ text }: { text: string }) {
  const [box, setBox] = useState<{ left: number; top: number } | null>(null);

  function place(target: HTMLElement) {
    const rect = target.getBoundingClientRect();
    setBox({ left: rect.left + rect.width / 2, top: rect.bottom + 8 });
  }

  function show(event: MouseEvent<HTMLElement> | FocusEvent<HTMLElement>) {
    place(event.currentTarget);
  }

  return (
    <span
      className="infotag"
      tabIndex={0}
      aria-label={text}
      onMouseEnter={show}
      onFocus={show}
      onMouseLeave={() => setBox(null)}
      onBlur={() => setBox(null)}
      onClick={(e) => e.stopPropagation()}
    >
      ?
      {box && (
        <span className="infotag__bubble" role="tooltip" style={{ left: box.left, top: box.top }}>
          {text}
        </span>
      )}
    </span>
  );
}
