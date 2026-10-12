locals {
  prefix    = "${var.name_prefix}-${var.environment}"
  aws_count = var.use_floci ? 0 : 1

  # Messaging topology — mirrors scripts/messaging_bootstrap.py exactly. Names are
  # intentionally un-prefixed so the app finds them by the same names locally and in AWS.
  topic_name = "platform-domain-events.fifo"

  queue_filters = {
    "order-processing.fifo"  = ["OrderSubmitted", "OrderAmended"]
    "order-delivery.fifo"    = ["OrderReadyForDelivery", "OrderCancellationRequested"]
    "order-fulfillment.fifo" = ["ShipmentRecorded", "InvoiceRecorded"]
    "projections.fifo"       = null
    "webhook-dispatch.fifo" = [
      "OrderSentToErp", "OrderConfirmed", "OrderClosed", "OrderRejected",
      "OrderRetrying", "OrderCancelled", "ShipmentRecorded", "InvoiceRecorded",
    ]
  }

  max_receive_count = 5

  # Secrets the app may read or create at runtime all live under this prefix.
  secret_arn_glob = local.aws_count == 0 ? "" : "arn:aws:secretsmanager:${var.region}:${data.aws_caller_identity.current[0].account_id}:secret:${local.prefix}/*"

  # Shared container environment for both the api and worker tasks. Only built in AWS mode
  # (compute isn't instantiated locally). DATABASE_URL carries the password.
  app_env = local.aws_count == 0 ? [] : [
    { name = "APP_PROFILE", value = "postgres" },
    { name = "DATABASE_URL", value = module.database[0].database_url },
    { name = "AWS_REGION", value = var.region },
    { name = "DOMAIN_TOPIC_ARN", value = module.messaging.topic_arn },
    { name = "ERP_ADAPTER_MODE", value = var.erp_adapter_mode },
    { name = "LOG_LEVEL", value = "INFO" },
    { name = "COGNITO_USER_POOL_ID", value = module.identity[0].user_pool_id },
    { name = "COGNITO_CLIENT_ID", value = module.identity[0].client_id },
    { name = "CORS_ALLOWED_ORIGINS", value = var.cors_allowed_origins },
  ]
}
