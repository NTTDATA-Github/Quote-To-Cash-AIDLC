import { Navigate, createBrowserRouter, useParams } from "react-router-dom";

import { AppShell } from "./App";
import { useAuth } from "./auth/AuthContext";
import { LoginPage } from "./features/auth/LoginPage";
import { OverviewPage } from "./features/admin/OverviewPage";
import { NotificationsPage } from "./features/admin/NotificationsPage";
import { ConnectionsPage } from "./features/admin/ConnectionsPage";
import { TenantsPage } from "./features/admin/TenantsPage";
import { SubsidiariesPage } from "./features/admin/SubsidiariesPage";
import { OrdersPage as OperatorOrdersPage } from "./features/admin/OrdersPage";
import { OrderDetailPage as OperatorOrderDetailPage } from "./features/admin/OrderDetailPage";
import { ConflictResolutionPage } from "./features/admin/ConflictResolutionPage";
import { MappingsPage } from "./features/admin/MappingsPage";
import { OrderEventsPage } from "./features/events/OrderEventsPage";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function HomeRedirect() {
  return <Navigate to="/admin/connections" replace />;
}

function OrderRedirect() {
  const { orderId } = useParams();
  return <Navigate to={`/admin/orders/${orderId}`} replace />;
}

function OrderEventsRedirect() {
  const { orderId } = useParams();
  return <Navigate to={`/admin/orders/${orderId}/events`} replace />;
}

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    path: "/",
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <HomeRedirect /> },
      { path: "admin/overview", element: <OverviewPage /> },
      { path: "notifications", element: <Navigate to="/admin/notifications" replace /> },
      { path: "orders/:orderId", element: <OrderRedirect /> },
      { path: "orders/:orderId/events", element: <OrderEventsRedirect /> },
      { path: "admin/notifications", element: <NotificationsPage /> },
      { path: "admin/orders", element: <OperatorOrdersPage /> },
      { path: "admin/orders/:orderId", element: <OperatorOrderDetailPage /> },
      { path: "admin/orders/:orderId/events", element: <OrderEventsPage /> },
      { path: "admin/subsidiaries", element: <SubsidiariesPage /> },
      { path: "admin/connections", element: <ConnectionsPage /> },
      { path: "admin/mappings", element: <MappingsPage /> },
      { path: "admin/tenants", element: <TenantsPage /> },
      { path: "admin/conflict-resolution", element: <ConflictResolutionPage /> },
    ],
  },
]);
