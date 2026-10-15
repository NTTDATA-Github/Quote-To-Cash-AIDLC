import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { graphqlRequest } from "../api/client";
import {
  BINDINGS_QUERY,
  CONNECTIONS_QUERY,
  CREATE_BINDING_MUTATION,
  CREATE_SUBSIDIARY_MUTATION,
  ERP_ROUTE_QUERY,
  SUBSIDIARIES_QUERY,
  RESELLERS_QUERY,
  RENAME_RESELLER_MUTATION,
  NOTIFICATIONS_QUERY,
  OPERATOR_ORDERS_QUERY,
  OPERATOR_ORDER_QUERY,
  PAUSE_CONNECTION_MUTATION,
  REGISTER_CONNECTION_MUTATION,
  REMOVE_BINDING_MUTATION,
  RESUME_CONNECTION_MUTATION,
  SET_ERP_ROUTE_MUTATION,
  TEST_ERP_ENDPOINT_MUTATION,
  VERIFY_BINDING_MUTATION,
  type Binding,
  type Connection,
  type Subsidiary,
  type Reseller,
  type NotificationDelivery,
  type OperatorOrder,
} from "../api/queries/admin";
import type { AuthConfigInput, ProbeSample } from "../api/queries/mapping";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../components/Toast";

// Orders move on their own timeline (worker-driven) — poll so status changes show up
// without a manual reload, which is most of what "the UI feels static" complaints were.
const LIVE_REFETCH_MS = 5000;

export function useNotifications() {
  const { idToken, isAuthenticated } = useAuth();
  return useQuery({
    queryKey: ["notifications"],
    queryFn: () =>
      graphqlRequest<{ notifications: NotificationDelivery[] }>("operator", NOTIFICATIONS_QUERY, {}, idToken).then(
        (d) => d.notifications,
      ),
    enabled: isAuthenticated,
    refetchInterval: LIVE_REFETCH_MS,
  });
}

export function useConnections() {
  const { idToken, isAuthenticated } = useAuth();
  return useQuery({
    queryKey: ["connections"],
    queryFn: () => graphqlRequest<{ connections: Connection[] }>("operator", CONNECTIONS_QUERY, {}, idToken).then((d) => d.connections),
    enabled: isAuthenticated,
  });
}

export function useBindings() {
  const { idToken, isAuthenticated } = useAuth();
  return useQuery({
    queryKey: ["bindings"],
    queryFn: () => graphqlRequest<{ bindings: Binding[] }>("operator", BINDINGS_QUERY, {}, idToken).then((d) => d.bindings),
    enabled: isAuthenticated,
  });
}

export function useErpRoute(subsidiaryId: string) {
  const { idToken, isAuthenticated } = useAuth();
  return useQuery({
    queryKey: ["erpRoute", subsidiaryId],
    queryFn: () =>
      graphqlRequest<{ erpRoute: { connectionId: string; erpCompanyId: string } | null }, { subsidiaryId: string }>(
        "operator",
        ERP_ROUTE_QUERY,
        { subsidiaryId },
        idToken,
      ).then((d) => d.erpRoute),
    enabled: isAuthenticated && !!subsidiaryId,
  });
}

export function useOperatorOrder(orderId: string) {
  const { idToken, isAuthenticated } = useAuth();
  return useQuery({
    queryKey: ["operatorOrder", orderId],
    queryFn: () =>
      graphqlRequest<{ order: OperatorOrder | null }, { orderId: string }>("operator", OPERATOR_ORDER_QUERY, { orderId }, idToken).then(
        (d) => d.order,
      ),
    enabled: isAuthenticated && !!orderId,
    refetchInterval: LIVE_REFETCH_MS,
  });
}

export function useOperatorOrders() {
  const { idToken, isAuthenticated } = useAuth();
  return useQuery({
    queryKey: ["operatorOrders"],
    queryFn: () =>
      graphqlRequest<{ orders: OperatorOrder[] }>("operator", OPERATOR_ORDERS_QUERY, {}, idToken).then((d) => d.orders),
    enabled: isAuthenticated,
    refetchInterval: LIVE_REFETCH_MS,
  });
}

export function useRegisterConnection() {
  const { idToken } = useAuth();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  return useMutation({
    mutationFn: (input: {
      erpType: string;
      instanceLabel: string;
      baseUrl: string;
      credentials: Record<string, string>;
      auth: AuthConfigInput;
      webhookSecretRef?: string;
    }) =>
      graphqlRequest<
        { registerConnection: { connectionId: string; hasAdapter: boolean; mappingStatus: string } },
        typeof input
      >(
        "operator",
        REGISTER_CONNECTION_MUTATION,
        input,
        idToken,
      ).then((d) => d.registerConnection),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      queryClient.invalidateQueries({ queryKey: ["mappableConnections"] });
      notify("Connection registered.");
    },
    onError: (err) => notify((err as Error).message, "danger"),
  });
}

export function usePauseConnection() {
  const { idToken } = useAuth();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  return useMutation({
    mutationFn: (input: { connectionId: string }) => graphqlRequest("operator", PAUSE_CONNECTION_MUTATION, input, idToken),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      notify("Connection paused — new orders will not be routed to it.");
    },
    onError: (err) => notify((err as Error).message, "danger"),
  });
}

export function useResumeConnection() {
  const { idToken } = useAuth();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  return useMutation({
    mutationFn: (input: { connectionId: string }) => graphqlRequest("operator", RESUME_CONNECTION_MUTATION, input, idToken),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      notify("Connection resumed.");
    },
    onError: (err) => notify((err as Error).message, "danger"),
  });
}

export function useTestErpEndpoint() {
  const { idToken } = useAuth();
  const { notify } = useToast();
  return useMutation({
    mutationFn: (input: { connectionId: string; path: string }) =>
      graphqlRequest<{ testErpEndpoint: ProbeSample }, typeof input>(
        "operator",
        TEST_ERP_ENDPOINT_MUTATION,
        input,
        idToken,
      ).then((d) => d.testErpEndpoint),
    onError: (err) => notify((err as Error).message, "danger"),
  });
}

export function useCreateBinding() {
  const { idToken } = useAuth();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  return useMutation({
    mutationFn: (input: { tenantId: string; connectionId: string; erpCustomerId: string; name: string }) =>
      graphqlRequest("operator", CREATE_BINDING_MUTATION, input, idToken),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["bindings"] });
      queryClient.invalidateQueries({ queryKey: ["resellers"] });
      notify("Reseller linked to connection.");
    },
    onError: (err) => notify((err as Error).message, "danger"),
  });
}

export function useVerifyBinding() {
  const { idToken } = useAuth();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  return useMutation({
    mutationFn: (input: { bindingId: string }) => graphqlRequest("operator", VERIFY_BINDING_MUTATION, input, idToken),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["bindings"] });
      notify("Customer link verified.");
    },
    onError: (err) => notify((err as Error).message, "danger"),
  });
}

export function useRemoveBinding() {
  const { idToken } = useAuth();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  return useMutation({
    mutationFn: (input: { bindingId: string }) => graphqlRequest("operator", REMOVE_BINDING_MUTATION, input, idToken),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["bindings"] });
      notify("Customer link removed.");
    },
    onError: (err) => notify((err as Error).message, "danger"),
  });
}

export function useSetErpRoute() {
  const { idToken } = useAuth();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  return useMutation({
    mutationFn: (input: { subsidiaryId: string; connectionId: string; erpCompanyId: string }) =>
      graphqlRequest("operator", SET_ERP_ROUTE_MUTATION, input, idToken),
    onSuccess: (_data, input) => {
      queryClient.invalidateQueries({ queryKey: ["erpRoute", input.subsidiaryId] });
      notify("Route saved.");
    },
    onError: (err) => notify((err as Error).message, "danger"),
  });
}

export function useSubsidiaries() {
  const { idToken, isAuthenticated } = useAuth();
  return useQuery({
    queryKey: ["subsidiaries"],
    queryFn: () =>
      graphqlRequest<{ subsidiaries: Subsidiary[] }>("operator", SUBSIDIARIES_QUERY, {}, idToken).then(
        (d) => d.subsidiaries,
      ),
    enabled: isAuthenticated,
  });
}

export function useResellers() {
  const { idToken, isAuthenticated } = useAuth();
  return useQuery({
    queryKey: ["resellers"],
    queryFn: () =>
      graphqlRequest<{ resellers: Reseller[] }>("operator", RESELLERS_QUERY, {}, idToken).then((d) => d.resellers),
    enabled: isAuthenticated,
  });
}

export function useRenameReseller() {
  const { idToken } = useAuth();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  return useMutation({
    mutationFn: (input: { tenantId: string; name: string }) =>
      graphqlRequest("operator", RENAME_RESELLER_MUTATION, input, idToken),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["resellers"] });
      notify("Reseller renamed.");
    },
    onError: (err) => notify((err as Error).message, "danger"),
  });
}

export function useCreateSubsidiary() {
  const { idToken } = useAuth();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  return useMutation({
    mutationFn: (input: { name: string; country: string; language: string }) =>
      graphqlRequest("operator", CREATE_SUBSIDIARY_MUTATION, input, idToken),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["subsidiaries"] });
      notify("Subsidiary created.");
    },
    onError: (err) => notify((err as Error).message, "danger"),
  });
}
