export interface Connection {
  connectionId: string;
  erpType: string;
  instanceLabel: string;
  baseUrl: string;
  credentials: Record<string, string>;
  authType: string;
  status: string;
  secretRef: string;
  hasWebhookSecret: boolean;
  // Derived from the adapter registry (ADR-0021), never stored — whether this erp_type
  // has working delivery code, not just a connection row.
  hasAdapter: boolean;
  // ADR-0022: NEEDS_MAPPING | MAPPING_IN_PROGRESS | AWAITING_ADAPTER | ADAPTER_READY — what
  // hasAdapter alone can't say, e.g. whether a mapping has already been approved and is
  // just waiting on adapter code to land.
  mappingStatus: string;
}

export interface Binding {
  bindingId: string;
  tenantId: string;
  connectionId: string;
  erpCustomerId: string;
  status: string;
}

export interface Money {
  // string, not number: the server sends Decimal-exact money as a string (fixed
  // 2026-10-04 — float couldn't represent e.g. 19.99 exactly). Parse with Number()
  // only for display formatting, never for further arithmetic.
  amount: string;
  currency: string;
}

export interface Subsidiary {
  subsidiaryId: string;
  name: string;
  country: string;
  language: string;
}

export interface Reseller {
  tenantId: string;
  name: string;
  webhookUrls: string[];
}

export interface OperatorOrderLine {
  lineId: string;
  productKey: string;
  quantity: number;
  unitOfMeasure: string;
  kind: string;
  unitPrice: Money | null;
  lineTotal: Money | null;
  shippedQuantity: number;
  deliveredQuantity: number;
  invoicedQuantity: number;
  scheduledDate: string | null;
}

export interface OperatorOrder {
  orderId: string;
  tenantId: string;
  clientReference: string;
  status: string;
  owningConnectionId: string | null;
  erpOrderId: string | null;
  lines: OperatorOrderLine[];
  timeline: { status: string; occurredAt: string }[];
  subtotal: Money | null;
  fulfillmentStatus: string;
  deliveryStatus: string;
  invoiceStatus: string;
  parties: { endCustomerName: string; shipTo: string; subsidiaryId: string; quoteId: string };
}

// One field the add/edit connection form asks for. `target` says where the value goes:
// LABEL, BASE_URL, CREDENTIAL (a non-secret parameter) or SECRET (stored, never returned).
export interface ErpField {
  key: string;
  label: string;
  hint: string;
  target: "LABEL" | "BASE_URL" | "CREDENTIAL" | "SECRET";
  secret: boolean;
}

// An ERP type the operator can connect without a developer. The form is built from this.
export interface ErpType {
  code: string;
  name: string;
  authType: string;
  fields: ErpField[];
}

export const ERP_TYPES_QUERY = /* GraphQL */ `
  query ErpTypes {
    erpTypes { code name authType fields { key label hint target secret } }
  }
`;

export const CONNECTIONS_QUERY = /* GraphQL */ `
  query Connections {
    connections { connectionId erpType instanceLabel baseUrl credentials authType status secretRef hasWebhookSecret hasAdapter mappingStatus }
  }
`;

export const BINDINGS_QUERY = /* GraphQL */ `
  query Bindings {
    bindings { bindingId tenantId connectionId erpCustomerId status }
  }
`;

export const SUBSIDIARIES_QUERY = /* GraphQL */ `
  query Subsidiaries {
    subsidiaries { subsidiaryId name country language }
  }
`;

export const RESELLERS_QUERY = /* GraphQL */ `
  query Resellers {
    resellers { tenantId name webhookUrls }
  }
`;

export const ERP_ROUTE_QUERY = /* GraphQL */ `
  query ErpRoute($subsidiaryId: String!) {
    erpRoute(subsidiaryId: $subsidiaryId) { connectionId erpCompanyId }
  }
`;

const OPERATOR_ORDER_FIELDS = /* GraphQL */ `
  orderId
  tenantId
  clientReference
  status
  owningConnectionId
  erpOrderId
  fulfillmentStatus
  deliveryStatus
  invoiceStatus
  parties { endCustomerName shipTo subsidiaryId quoteId }
  lines {
    lineId productKey quantity unitOfMeasure kind
    unitPrice { amount currency } lineTotal { amount currency }
    shippedQuantity deliveredQuantity invoicedQuantity scheduledDate
  }
  timeline { status occurredAt }
  subtotal { amount currency }
`;

export const OPERATOR_ORDER_QUERY = /* GraphQL */ `
  query OperatorOrder($orderId: String!) { order(orderId: $orderId) { ${OPERATOR_ORDER_FIELDS} } }
`;

export const OPERATOR_ORDERS_QUERY = /* GraphQL */ `
  query OperatorOrders { orders { ${OPERATOR_ORDER_FIELDS} } }
`;

export const REGISTER_CONNECTION_MUTATION = /* GraphQL */ `
  mutation RegisterConnection(
    $erpType: String!
    $instanceLabel: String!
    $baseUrl: String!
    $credentials: JSON!
    $auth: AuthConfigInput!
    $webhookSecretRef: String
  ) {
    registerConnection(
      erpType: $erpType
      instanceLabel: $instanceLabel
      baseUrl: $baseUrl
      credentials: $credentials
      auth: $auth
      webhookSecretRef: $webhookSecretRef
    ) {
      connectionId
      hasAdapter
      mappingStatus
    }
  }
`;

export const UPDATE_CONNECTION_MUTATION = /* GraphQL */ `
  mutation UpdateConnection(
    $connectionId: String!
    $instanceLabel: String!
    $baseUrl: String!
    $credentials: JSON!
    $secret: String
  ) {
    updateConnection(
      connectionId: $connectionId
      instanceLabel: $instanceLabel
      baseUrl: $baseUrl
      credentials: $credentials
      secret: $secret
    ) { connectionId instanceLabel baseUrl status }
  }
`;

// Adds a webhook URL for a reseller. `signingSecret` comes back once, so the operator
// must copy it to the reseller straight away.
export const REGISTER_RESELLER_WEBHOOK_MUTATION = /* GraphQL */ `
  mutation RegisterResellerWebhook(
    $tenantId: String!
    $name: String!
    $url: String!
    $authType: String!
    $authParams: JSON
    $authSecret: String
  ) {
    registerResellerWebhook(
      tenantId: $tenantId
      name: $name
      url: $url
      authType: $authType
      authParams: $authParams
      authSecret: $authSecret
    ) {
      endpoint { endpointId name url isActive authType }
      signingSecret
    }
  }
`;

// A delivery that failed or was rejected, waiting for an operator. View-only for now.
// The kind of problem behind a conflict. Computed by the API from the ERP's message.
export type ConflictCategory =
  | "CUSTOMER_ON_HOLD"
  | "PRODUCT_NOT_FOUND"
  | "PRICE_MISMATCH"
  | "ADDRESS_PROBLEM"
  | "DUPLICATE_ORDER"
  | "ERP_UNREACHABLE"
  | "OTHER";

export interface OrderConflict {
  conflictId: string;
  tenantId: string;
  orderId: string;
  reasonCode: string;
  reason: string;
  severity: "HIGH" | "MEDIUM" | "LOW";
  status: "OPEN" | "IN_REVIEW" | "RESOLVED" | "DISMISSED";
  attempts: number;
  openedAt: string;
  slaDueAt: string;
  resolvedAt: string | null;
  resolutionNote: string;
  category: ConflictCategory;
  categorySource: "RULE" | "AI" | "UNRECOGNISED";
}

// An AI summary of one conflict. `text` is set when one was written; otherwise `unavailable`
// says why not.
export interface ConflictExplanation {
  text: string | null;
  unavailable: string | null;
}

// How urgent one cause is, by whether the ERP refused the order or delivery is retrying.
export interface SeverityRule {
  category: ConflictCategory;
  label: string;
  whenRejected: "HIGH" | "MEDIUM" | "LOW";
  whenRetrying: "HIGH" | "MEDIUM" | "LOW";
}

export const SEVERITY_RULES_QUERY = /* GraphQL */ `
  query SeverityRules {
    conflictSeverityRules { category label whenRejected whenRetrying }
  }
`;

export const SET_SEVERITY_RULE_MUTATION = /* GraphQL */ `
  mutation SetSeverityRule($category: String!, $whenRejected: String!, $whenRetrying: String!) {
    setConflictSeverityRule(category: $category, whenRejected: $whenRejected, whenRetrying: $whenRetrying) {
      category label whenRejected whenRetrying
    }
  }
`;

export const CONFLICT_EXPLANATION_QUERY = /* GraphQL */ `
  query ConflictExplanation($conflictId: String!) {
    conflictExplanation(conflictId: $conflictId) { text unavailable }
  }
`;

export const ORDER_CONFLICTS_QUERY = /* GraphQL */ `
  query OrderConflicts($status: String) {
    orderConflicts(status: $status) {
      conflictId tenantId orderId reasonCode reason severity status attempts
      openedAt slaDueAt resolvedAt resolutionNote category categorySource
    }
  }
`;

// The webhook URLs of one reseller, paused ones included, with the auth type (never the secret).
export interface WebhookEndpoint {
  endpointId: string;
  name: string;
  url: string;
  isActive: boolean;
  authType: string;
}

export const WEBHOOK_ENDPOINTS_QUERY = /* GraphQL */ `
  query WebhookEndpoints($tenantId: String!) {
    webhookEndpoints(tenantId: $tenantId) { endpointId name url isActive authType }
  }
`;

export const PAUSE_WEBHOOK_ENDPOINT_MUTATION = /* GraphQL */ `
  mutation PauseWebhookEndpoint($tenantId: String!, $endpointId: String!) {
    pauseWebhookEndpoint(tenantId: $tenantId, endpointId: $endpointId) { endpointId isActive }
  }
`;

export const RESUME_WEBHOOK_ENDPOINT_MUTATION = /* GraphQL */ `
  mutation ResumeWebhookEndpoint($tenantId: String!, $endpointId: String!) {
    resumeWebhookEndpoint(tenantId: $tenantId, endpointId: $endpointId) { endpointId isActive }
  }
`;

export const CANCEL_ORDER_MUTATION = /* GraphQL */ `
  mutation CancelOrder($orderId: String!, $reason: String!) {
    cancelOrder(orderId: $orderId, reason: $reason)
  }
`;

export const CREATE_BINDING_MUTATION = /* GraphQL */ `
  mutation CreateBinding($tenantId: String!, $connectionId: String!, $erpCustomerId: String!, $name: String!) {
    createBinding(tenantId: $tenantId, connectionId: $connectionId, erpCustomerId: $erpCustomerId, name: $name) {
      bindingId
    }
  }
`;

export const VERIFY_BINDING_MUTATION = /* GraphQL */ `
  mutation VerifyBinding($bindingId: String!) {
    verifyBinding(bindingId: $bindingId) { bindingId status }
  }
`;

export const RENAME_RESELLER_MUTATION = /* GraphQL */ `
  mutation RenameReseller($tenantId: String!, $name: String!) {
    renameReseller(tenantId: $tenantId, name: $name) { tenantId name }
  }
`;

export const SET_ERP_ROUTE_MUTATION = /* GraphQL */ `
  mutation SetErpRoute($subsidiaryId: String!, $connectionId: String!, $erpCompanyId: String!) {
    setErpRoute(subsidiaryId: $subsidiaryId, connectionId: $connectionId, erpCompanyId: $erpCompanyId) {
      subsidiaryId
    }
  }
`;

export const PAUSE_CONNECTION_MUTATION = /* GraphQL */ `
  mutation PauseConnection($connectionId: String!) {
    pauseConnection(connectionId: $connectionId) { connectionId status }
  }
`;

export const RESUME_CONNECTION_MUTATION = /* GraphQL */ `
  mutation ResumeConnection($connectionId: String!) {
    resumeConnection(connectionId: $connectionId) { connectionId status }
  }
`;

// Reachability + auth check against an existing connection's stored base URL/credentials
// (ADR-0021). Unlike probeErpSamples it works for any connection, adapter or not — it's a
// plain "can we reach it", not part of the mapping-onboarding flow.
export const TEST_ERP_ENDPOINT_MUTATION = /* GraphQL */ `
  mutation TestErpEndpoint($connectionId: String!, $path: String!) {
    testErpEndpoint(connectionId: $connectionId, path: $path) { label text error }
  }
`;

export const REMOVE_BINDING_MUTATION = /* GraphQL */ `
  mutation RemoveBinding($bindingId: String!) {
    removeBinding(bindingId: $bindingId) { bindingId status }
  }
`;

export const CREATE_SUBSIDIARY_MUTATION = /* GraphQL */ `
  mutation CreateSubsidiary($name: String!, $country: String!, $language: String!) {
    createSubsidiary(name: $name, country: $country, language: $language) {
      subsidiaryId
    }
  }
`;

export interface NotificationDelivery {
  deliveryId: string;
  tenantId: string;
  endpointId: string;
  orderId: string;
  eventType: string;
  occurredAt: string;
  status: string;
  attempts: number;
  lastResponse: string | null;
}

export const NOTIFICATIONS_QUERY = /* GraphQL */ `
  query Notifications {
    notifications {
      deliveryId tenantId endpointId orderId eventType occurredAt status attempts lastResponse
    }
  }
`;
