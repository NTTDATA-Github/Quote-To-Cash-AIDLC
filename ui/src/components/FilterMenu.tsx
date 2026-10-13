import { useEffect, useRef, useState } from "react";
import { Check, ListFilter } from "lucide-react";

export interface FilterGroup {
  label: string;
  /** First option should be the "no filter" value, conventionally "all". */
  options: { value: string; label: string }[];
  value: string;
  onChange: (value: string) => void;
}

/** One filter entry point, used identically on every list page — whether it has one
 * filterable dimension or three, it is always this same button-and-panel, never a
 * different widget per page (a row of pill buttons reads fine at 4 options and turns
 * into a wrapping mess at 9; a vertical list in a panel doesn't care how many there
 * are). "Active" means a group's value isn't its own first ("all") option. */
export function FilterMenu({ groups }: { groups: FilterGroup[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const activeCount = groups.filter((g) => g.value !== g.options[0]?.value).length;

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div className="filtermenu" ref={ref}>
      <button
        type="button"
        className="filtermenu__btn"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <ListFilter size={15} strokeWidth={2} />
        Filters
        {activeCount > 0 && <span className="filtermenu__count">{activeCount}</span>}
      </button>
      {open && (
        <div className="filtermenu__panel" role="menu">
          {groups.map((g) => (
            <div className="filtermenu__group" key={g.label}>
              <div className="filtermenu__label">{g.label}</div>
              {g.options.map((o) => (
                <button
                  key={o.value}
                  type="button"
                  className="filtermenu__opt"
                  role="menuitemradio"
                  aria-checked={g.value === o.value}
                  onClick={() => g.onChange(o.value)}
                >
                  <Check size={14} strokeWidth={2.5} className="filtermenu__check" />
                  {o.label}
                </button>
              ))}
            </div>
          ))}
          {activeCount > 0 && (
            <button
              type="button"
              className="filtermenu__clear"
              onClick={() => groups.forEach((g) => g.onChange(g.options[0]?.value ?? "all"))}
            >
              Clear filters
            </button>
          )}
        </div>
      )}
    </div>
  );
}
