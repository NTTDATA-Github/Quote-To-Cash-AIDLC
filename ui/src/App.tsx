import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "./auth/AuthContext";

const ADMIN_NAV = [
  {
    label: "Run",
    items: [
      { to: "/admin/orders", label: "Orders" },
      { to: "/admin/notifications", label: "Notifications" },
      { to: "/admin/failed-messages", label: "Failed messages" },
    ],
  },
  {
    label: "Set up",
    items: [
      { to: "/admin/connections", label: "ERP connections" },
      { to: "/admin/subsidiaries", label: "Subsidiaries" },
      { to: "/admin/tenants", label: "Resellers" },
      { to: "/admin/mappings", label: "ERP mapping" },
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
          <div className="brandmark">AdminOps</div>
          <div className="role">Distributor</div>
        </div>
        <nav className="nav" aria-label="Main">
          {ADMIN_NAV.map((group) => (
            <div key={group.label} className="nav-group">
              <div className="nav-label">{group.label}</div>
              {group.items.map((n) => (
                <NavLink key={n.to} to={n.to} className={({ isActive }) => `nav-item ${isActive ? "is-active" : ""}`}>
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
              Sign out
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
