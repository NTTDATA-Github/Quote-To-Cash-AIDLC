import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRightLeft,
  Bell,
  Building2,
  LayoutDashboard,
  Plug,
  ShoppingCart,
  Users,
  Workflow,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { ProductTour, TOUR_DISMISSED_KEY } from "./components/ProductTour";
import { UserMenu } from "./components/UserMenu";
import type { HeaderSlot } from "./components/PageHeader";

const ADMIN_NAV: { label: string; items: { to: string; label: string; icon: LucideIcon }[] }[] = [
  {
    label: "Overview",
    items: [{ to: "/admin/overview", label: "Dashboard", icon: LayoutDashboard }],
  },
  {
    label: "Operations",
    items: [
      { to: "/admin/orders", label: "Orders", icon: ShoppingCart },
      { to: "/admin/notifications", label: "Notifications", icon: Bell },
      { to: "/admin/failed-messages", label: "Failed messages", icon: AlertTriangle },
    ],
  },
  {
    label: "Settings",
    items: [
      { to: "/admin/connections", label: "ERP connections", icon: Plug },
      { to: "/admin/subsidiaries", label: "Subsidiaries", icon: Building2 },
      { to: "/admin/tenants", label: "Resellers", icon: Users },
      { to: "/admin/mappings", label: "ERP mapping", icon: Workflow },
    ],
  },
];

export function AppShell() {
  const [headerSlot, setHeaderSlot] = useState<HeaderSlot>(null);
  // Shown once per browser, right after login (ask-once, see TOUR_DISMISSED_KEY) — the
  // operator can bring it back later from the user menu.
  const [tourOpen, setTourOpen] = useState(false);
  useEffect(() => {
    try {
      if (localStorage.getItem(TOUR_DISMISSED_KEY) !== "1") setTourOpen(true);
    } catch {
      setTourOpen(true);
    }
  }, []);

  return (
    <div className="app">
      <aside className="side">
        <div className="brand">
          <div className="brand__mark">
            <ArrowRightLeft size={18} strokeWidth={2.25} />
          </div>
          <div className="brand__text">
            <span className="brand__name">Order-to-Cash</span>
            <span className="brand__sub">Operator Console</span>
          </div>
        </div>
        <nav className="nav" aria-label="Main">
          {ADMIN_NAV.map((group) => (
            <div key={group.label} className="nav-group">
              <div className="nav-label">{group.label}</div>
              {group.items.map((n) => (
                <NavLink key={n.to} to={n.to} className={({ isActive }) => `nav-item ${isActive ? "is-active" : ""}`}>
                  <n.icon size={16} strokeWidth={2} />
                  {n.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="side-foot">
          <span className="side-foot__label">Powered by</span>
          <img className="side-foot__logo" src="/ntt-logo.png" alt="NTT" />
        </div>
      </aside>
      <div className="main">
        <header className="top">
          <div className="top-title" ref={setHeaderSlot} />
          <div className="top-tools">
            <UserMenu onStartTour={() => setTourOpen(true)} />
          </div>
        </header>
        <main className="content">
          <Outlet context={headerSlot} />
        </main>
      </div>
      <ProductTour open={tourOpen} onClose={() => setTourOpen(false)} />
    </div>
  );
}
