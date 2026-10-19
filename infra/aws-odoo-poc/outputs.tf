output "odoo_url" {
  value = "http://${aws_instance.odoo.public_ip}:8069"
}

output "odoo_https_url" {
  description = "Self-signed cert -- browser will warn, click through (Advanced -> Proceed)."
  value       = "https://${aws_instance.odoo.public_ip}"
}

output "public_ip" {
  value = aws_instance.odoo.public_ip
}
