import { NavLink, Outlet, useLocation } from "react-router-dom";
import { AlertTriangle, Bell, Boxes, Building2, LogOut, Plug, ShoppingCart, Users, Workflow } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { useAuth } from "./auth/AuthContext";

const ADMIN_NAV: { label: string; items: { to: string; label: string; icon: LucideIcon }[] }[] = [
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

function crumbFor(pathname: string): string {
  if (/^\/orders\/[^/]+\/events$/.test(pathname)) return "Notifications / Order events";
  if (/^\/orders\/[^/]+$/.test(pathname)) return "Notifications / Order";
  if (pathname.startsWith("/admin/notifications")) return "AdminOps / Notifications";
  if (pathname.startsWith("/admin/orders")) return "AdminOps / Orders";
  if (pathname.startsWith("/admin/subsidiaries")) return "AdminOps / Subsidiaries";
  if (pathname.startsWith("/admin/connections")) return "AdminOps / ERP connections";
  if (pathname.startsWith("/admin/mappings")) return "AdminOps / ERP mapping";
  if (pathname.startsWith("/admin/tenants")) return "AdminOps / Resellers";
  if (pathname.startsWith("/admin/failed-messages")) return "AdminOps / Failed messages";
  return "";
}

export function AppShell() {
  const { tenantId, roles, signOut } = useAuth();
  const location = useLocation();
  return (
    <div className="app">
      <aside className="side">
        <div>
          <div className="brandmark">
            <Boxes size={18} strokeWidth={2.25} /> AdminOps
          </div>
          <div className="role">Distributor</div>
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
        <div className="side-note">{tenantId ? `Signed in to tenant ${tenantId}` : "Signed in"}</div>
      </aside>
      <div className="main">
        <header className="top">
          <div className="crumb">{crumbFor(location.pathname)}</div>
          <div className="user">
            <span>{roles.join(", ") || "User"}</span>
            <button className="erp-btn erp-btn--ghost erp-btn--sm" type="button" onClick={signOut}>
              <LogOut size={14} strokeWidth={2} /> Sign out
            </button>
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
