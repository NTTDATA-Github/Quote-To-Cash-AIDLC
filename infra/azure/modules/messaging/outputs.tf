output "namespace_id" {
  value = azurerm_servicebus_namespace.main.id
}

output "namespace_fqdn" {
  value = "${azurerm_servicebus_namespace.main.name}.servicebus.windows.net"
}

output "topic_name" {
  value = azurerm_servicebus_topic.domain_events.name
}
