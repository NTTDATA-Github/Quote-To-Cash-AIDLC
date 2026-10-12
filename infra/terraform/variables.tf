variable "use_floci" {
  description = "true = provision only what floci emulates (SNS/SQS/Secrets/Cognito) for local dev; false = full AWS."
  type        = bool
  default     = false
}

variable "floci_endpoint" {
  description = "floci endpoint used when use_floci=true."
  type        = string
  default     = "http://localhost:4566"
}

variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (used in resource names/tags). Single env for now."
  type        = string
  default     = "staging"
}

variable "name_prefix" {
  description = "Short prefix for AWS resource names (kept under the 32-char ALB/target-group limit)."
  type        = string
  default     = "o2c"
}

# ---------------------------------------------------------------------------
# PUBLIC ACCESS — deliberately exposes the stack to the internet for easy debugging.
# true  = Aurora is publicly_accessible, Fargate tasks get public IPs, and security
#         groups allow the DB/app ports from 0.0.0.0/0. Convenient, and NOT safe for real
#         data: a public multi-tenant Postgres is one of the most-scanned things on AWS.
# false = Aurora + Fargate private; reach the DB via ECS Exec or an SSM tunnel instead.
# Flipping this to false is the single lever to lock the environment down later.
# Note: this controls NETWORK reachability only. Cognito JWT auth, the DB password, and
# Secrets Manager are always on — "public" never means "unauthenticated".
# ---------------------------------------------------------------------------
variable "public_access" {
  description = "Expose Aurora + Fargate directly to the internet (debug convenience; unsafe for real data)."
  type        = bool
  default     = false
}

variable "vpc_cidr" {
  description = "CIDR for the VPC."
  type        = string
  default     = "10.20.0.0/16"
}

variable "db_name" {
  description = "Aurora database name."
  type        = string
  default     = "portal"
}

variable "db_username" {
  description = "Aurora master username."
  type        = string
  default     = "portal"
}

variable "db_password" {
  description = "Aurora master password. Supply via TF_VAR_db_password (never commit it)."
  type        = string
  sensitive   = true
  default     = ""
}

variable "aurora_min_acu" {
  description = "Aurora Serverless v2 minimum capacity units."
  type        = number
  default     = 0.5
}

variable "aurora_max_acu" {
  description = "Aurora Serverless v2 maximum capacity units."
  type        = number
  default     = 4
}

variable "api_image" {
  description = "Full ECR image ref for the api (repo:tag). CD sets this to the commit SHA tag."
  type        = string
  default     = ""
}

variable "worker_image" {
  description = "Full ECR image ref for the worker (repo:tag). CD sets this to the commit SHA tag."
  type        = string
  default     = ""
}

variable "api_desired_count" {
  description = "Number of api tasks."
  type        = number
  default     = 1
}

variable "worker_desired_count" {
  description = "Number of worker tasks."
  type        = number
  default     = 1
}

variable "task_cpu" {
  description = "Fargate task CPU units."
  type        = number
  default     = 512
}

variable "task_memory" {
  description = "Fargate task memory (MiB)."
  type        = number
  default     = 1024
}

variable "odoo_image" {
  description = "Full ECR image ref for Odoo (repo:tag). Empty uses <registry>/o2c/odoo:bootstrap."
  type        = string
  default     = ""
}

variable "odoo_db_password" {
  description = "Password for the Odoo RDS user. Supply via TF_VAR_odoo_db_password (never commit it). Not the Aurora password."
  type        = string
  sensitive   = true
  default     = ""
}

variable "odoo_secret_value" {
  description = "Initial Odoo connection secret JSON stored in Secrets Manager. Supply via TF_VAR_odoo_secret_value; empty = placeholder."
  type        = string
  sensitive   = true
  default     = ""
}

variable "erp_adapter_mode" {
  description = "ERP dispatch mode: 'real' (adapter registry) or 'stub' (StubErpAdapter for every ERP)."
  type        = string
  default     = "real"
}

variable "acm_certificate_arn" {
  description = "ACM cert ARN for the ALB HTTPS listener. Empty = serve HTTP on :80 (cert-less staging)."
  type        = string
  default     = ""
}

variable "cors_allowed_origins" {
  description = "Comma-separated UI origins allowed by the api (CloudFront/S3 URL in AWS)."
  type        = string
  default     = "*"
}

variable "github_oidc_repo" {
  description = "GitHub repo (owner/name) allowed to assume the CI deploy role via OIDC. Empty = skip creating the role."
  type        = string
  default     = ""
}
