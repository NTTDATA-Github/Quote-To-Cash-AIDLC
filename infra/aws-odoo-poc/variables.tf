variable "region" {
  type    = string
  default = "us-east-1"
}

variable "instance_type" {
  description = "Odoo wants more than 1GB RAM; t3.small (2GB) is the practical minimum."
  type        = string
  default     = "t3.small"
}

# POC convenience:
# open to the internet behind a password only. Narrow to your IP (e.g. "1.2.3.4/32") for
# anything beyond a throwaway demo.
variable "allowed_cidr" {
  type    = string
  default = "0.0.0.0/0"
}

# Optional: set to an existing EC2 key pair name if you want SSH access to debug.
# Not needed just to reach Odoo over 8069.
variable "key_name" {
  type    = string
  default = null
}
