# Service Bus topic -> subscriptions. Replaces SNS FIFO topic -> SQS FIFO queues + DLQs.
# A subscription IS the queue; dead-lettering is built into every subscription, so there
# is no separate DLQ resource or queue policy here (unlike infra/terraform's messaging
# module, which creates both).
#
# FIFO equivalence: `requires_session = true` + the publisher setting SessionId
# (= today's SNS MessageGroupId) on every message. `support_ordering` on the topic keeps
# delivery-order guarantees end to end. Both this and `requires_duplicate_detection` are
# fixed at creation (ForceNew) — do not flip them after the first apply without recreating
# the entity.
#
# Filters: SNS's `filter_policy` (matched against MessageAttributes) becomes a SQL filter
# matched against a custom application property the publisher sets on each message
# (`eventType` — see the new messaging/azure.py adapter). A subscription with no filter
# gets `null` here and keeps the default `$Default` TrueFilter (receives everything,
# same as `queue_filters[...] == null` on the AWS side).

resource "azurerm_servicebus_namespace" "main" {
  # Namespace names may not end in "-sb"/"-mgmt" (reserved suffixes).
  name                = "${var.prefix}-messaging"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "Standard" # Basic has no topics
}

resource "azurerm_servicebus_topic" "domain_events" {
  name                         = var.topic_name
  namespace_id                 = azurerm_servicebus_namespace.main.id
  support_ordering             = true
  requires_duplicate_detection = false
}

resource "azurerm_servicebus_subscription" "work" {
  for_each            = var.subscription_filters
  name                = each.key
  topic_id            = azurerm_servicebus_topic.domain_events.id
  max_delivery_count  = var.max_delivery_count
  requires_session    = true
  default_message_ttl = "P14D" # 14 days, matches the AWS DLQ's message_retention_seconds
}

# A *named* rule, not "$Default": the azurerm provider (confirmed empirically, v4.81.0)
# cannot reliably create OR update a azurerm_servicebus_subscription_rule literally named
# "$Default" — it reports "Provider produced inconsistent result after apply" and
# silently deletes the rule without recreating it, on both the create and update paths.
# Filed against the provider; worked around here by managing a separate, genuinely-new
# rule name instead.
#
# Because the subscription's auto-created "$Default" TrueFilter rule is NOT touched by
# Terraform, and rules are OR'd within a subscription, that rule must be deleted
# out-of-band (one-time, not Terraform-managed — see docs/deploy-azure.md) or it will
# keep matching everything regardless of this filter.
resource "azurerm_servicebus_subscription_rule" "filter" {
  for_each        = { for name, types in var.subscription_filters : name => types if types != null }
  name            = "event-type-filter"
  subscription_id = azurerm_servicebus_subscription.work[each.key].id
  filter_type     = "SqlFilter"
  sql_filter      = join(" OR ", [for t in each.value : "eventType = '${t}'"])
}
