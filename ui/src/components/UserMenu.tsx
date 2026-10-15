import { useEffect, useRef, useState } from "react";
import { Compass, LogOut, Moon, Sun } from "lucide-react";

import { useAuth } from "../auth/AuthContext";
import { useTheme } from "../theme/ThemeContext";

function initials(value: string | null): string {
  if (!value) return "OP";
  const parts = value.replace(/[^a-zA-Z0-9]+/g, " ").trim().split(" ");
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/** Click the avatar to open — a hover-opened menu that contains Sign out is a known
 * anti-pattern (a stray mouse-over signs you out of nothing, but it trains the wrong
 * habit and is unreachable on touch). Closes on Escape or an outside click. */
export function UserMenu({ onStartTour }: { onStartTour: () => void }) {
  const { email, username, roles, signOut } = useAuth();
  const { theme, toggle } = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const roleLabel = roles.join(", ") || "Operator";
  const identity = email ?? username ?? roleLabel;

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
    <div className="usermenu" ref={ref}>
      <button
        type="button"
        className="avatar avatar--button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="User menu"
        onClick={() => setOpen((v) => !v)}
      >
        {initials(roles[0] ?? username ?? email)}
      </button>
      {open && (
        <div className="usermenu__panel" role="menu">
          <div className="usermenu__who">
            <div className="usermenu__name">{identity}</div>
            <div className="usermenu__role">{roleLabel}</div>
          </div>
          <button type="button" className="usermenu__item" role="menuitem" onClick={toggle}>
            {theme === "dark" ? <Sun size={15} strokeWidth={2} /> : <Moon size={15} strokeWidth={2} />}
            {theme === "dark" ? "Light theme" : "Dark theme"}
          </button>
          <button
            type="button"
            className="usermenu__item"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onStartTour();
            }}
          >
            <Compass size={15} strokeWidth={2} />
            Product tour
          </button>
          <button
            type="button"
            className="usermenu__item usermenu__item--danger"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              signOut();
            }}
          >
            <LogOut size={15} strokeWidth={2} />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
