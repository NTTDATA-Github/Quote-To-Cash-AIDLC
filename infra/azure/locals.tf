locals {
  prefix = "${var.name_prefix}-${var.environment}" # "o2c-staging" — used for hyphen-safe names
  suffix = random_string.suffix.result             # for globally-unique names (storage/acr/kv)

  # Alphanumeric-only, no hyphens: Storage Account / ACR / Key Vault name rules.
  prefix_alnum = replace(local.prefix, "-", "")

  # Messaging topology — same 5 subscriptions + filters as infra/terraform's queue_filters,
  # renamed for Service Bus (no ".fifo" suffix convention; sessions give FIFO instead).
  topic_name = "platform-domain-events"

  subscription_filters = {
    "order-processing"  = ["OrderSubmitted", "OrderAmended"]
    "order-delivery"    = ["OrderReadyForDelivery", "OrderCancellationRequested"]
    "order-fulfillment" = ["ShipmentRecorded", "InvoiceRecorded"]
    "projections"       = null
    "webhook-dispatch" = [
      "OrderSentToErp", "OrderConfirmed", "OrderClosed", "OrderRejected",
      "OrderRetrying", "OrderCancelled", "ShipmentRecorded", "InvoiceRecorded",
    ]
  }

  max_delivery_count = 5

  # Shared container environment for both the api and worker apps.
  app_env = [
    { name = "APP_PROFILE", value = "postgres" },
    { name = "DATABASE_URL", value = module.database.database_url },
    { name = "CLOUD_PROVIDER", value = "azure" },
    { name = "AZURE_SERVICEBUS_NAMESPACE", value = module.messaging.namespace_fqdn },
    { name = "DOMAIN_TOPIC_NAME", value = module.messaging.topic_name },
    { name = "AZURE_KEY_VAULT_URI", value = module.secrets.vault_uri },
    { name = "ERP_ADAPTER_MODE", value = var.erp_adapter_mode },
    { name = "LOG_LEVEL", value = "INFO" },
    { name = "ENTRA_TENANT_ID", value = var.entra_tenant_id },
    # Ternary, not coalesce(): coalesce() also rejects "" as a non-match, so it errors
    # with nothing left to return when client_id is null. module.identity.client_id is
    # null when var.create_entra_app=false, and Container Apps' env value must be a real
    # string. Empty string is exactly what makes composition._resolve_identity_provider
    # fall back to the header stub, same as an unset COGNITO_CLIENT_ID on the AWS path.
    { name = "ENTRA_CLIENT_ID", value = module.identity.client_id != null ? module.identity.client_id : "" },
    { name = "CORS_ALLOWED_ORIGINS", value = var.cors_allowed_origins },
    # Mapping service uses OpenAI (gpt-4o) via Azure Foundry; pass endpoint to enable it
    { name = "FOUNDRY_ENDPOINT", value = module.foundry.foundry_endpoint },
    { name = "MAPPING_LLM_PROVIDER", value = "openai" },
  ]
}
