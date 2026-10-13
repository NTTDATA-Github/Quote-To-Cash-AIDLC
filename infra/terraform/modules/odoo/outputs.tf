output "alb_dns_name" {
  value = aws_lb.odoo.dns_name
}

output "db_endpoint" {
  description = "Private RDS host. Only the Odoo task can connect."
  value       = aws_db_instance.odoo.address
}

output "service_name" {
  value = aws_ecs_service.odoo.name
}

output "image" {
  description = "The image this apply ran with (not raw var.odoo_image — the resolved value main.tf passed in). CI reads this to keep reapplying it when it isn't rebuilding Odoo."
  value       = var.odoo_image
}
