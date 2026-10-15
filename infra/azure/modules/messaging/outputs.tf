output "namespace_id" {
  value = azurerm_servicebus_namespace.main.id
}

output "namespace_fqdn" {
  value = "${azurerm_servicebus_namespace.main.name}.servicebus.windows.net"
}

output "topic_name" {
  value = azurerm_servicebus_topic.domain_events.name
}

output "worker_connection_string" {
  value     = azurerm_servicebus_namespace_authorization_rule.worker.primary_connection_string
  sensitive = true
}
