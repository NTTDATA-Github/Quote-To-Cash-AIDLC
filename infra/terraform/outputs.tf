# Messaging + secrets exist in both floci and AWS modes.
output "domain_topic_arn" {
  description = "SNS FIFO topic ARN (set as DOMAIN_TOPIC_ARN on the app)."
  value       = module.messaging.topic_arn
}

output "work_queue_urls" {
  description = "SQS FIFO work-queue URLs by name."
  value       = module.messaging.work_queue_urls
}

output "dlq_urls" {
  description = "SQS FIFO dead-letter-queue URLs by name."
  value       = module.messaging.dlq_urls
}

output "odoo_secret_arn" {
  description = "Secrets Manager ARN for the Odoo connection secret."
  value       = module.secrets.odoo_secret_arn
}

# AWS-only outputs (null when use_floci=true).
output "odoo_alb_dns_name" {
  description = "Public DNS name for Odoo. Open http://<this> . The database is not on this host."
  value       = one(module.odoo[*].alb_dns_name)
}

output "odoo_db_endpoint" {
  description = "Private Postgres 15 host for Odoo. Only the Odoo task can connect."
  value       = one(module.odoo[*].db_endpoint)
}

output "ecr_odoo_repository_url" {
  description = "ECR repo URL for the Odoo image."
  value       = one(module.registry[*].odoo_repository_url)
}

output "odoo_image" {
  description = "The image Odoo's task definition currently runs. CI re-passes this on applies that aren't rebuilding Odoo, so an apply never resets it to the (unpushed) :bootstrap default."
  value       = one(module.odoo[*].image)
}

output "alb_dns_name" {
  description = "Public ALB DNS name — the app's entry point."
  value       = one(module.compute[*].alb_dns_name)
}

output "aurora_endpoint" {
  description = "Aurora writer endpoint (host). Public when public_access=true."
  value       = one(module.database[*].cluster_endpoint)
}

output "ecr_api_repository_url" {
  description = "ECR repo URL for the api image."
  value       = one(module.registry[*].api_repository_url)
}

output "ecr_worker_repository_url" {
  description = "ECR repo URL for the worker image."
  value       = one(module.registry[*].worker_repository_url)
}

output "cognito_user_pool_id" {
  description = "Cognito user pool id (COGNITO_USER_POOL_ID)."
  value       = one(module.identity[*].user_pool_id)
}

output "cognito_client_id" {
  description = "Cognito SPA app client id (COGNITO_CLIENT_ID)."
  value       = one(module.identity[*].client_id)
}

output "ecs_cluster_name" {
  description = "ECS cluster name (for aws ecs execute-command / update-service)."
  value       = one(module.compute[*].cluster_name)
}

output "github_deploy_role_arn" {
  description = "IAM role ARN for GitHub Actions OIDC. Null if github_oidc_repo unset."
  value       = one(module.iam[*].github_deploy_role_arn)
}

output "public_access" {
  description = "Whether Aurora + Fargate are internet-exposed in this environment."
  value       = var.public_access
}

# Used by the deploy workflow to run the Alembic migration as a one-off ECS task.
output "app_subnet_ids" {
  description = "Public subnet ids the Fargate tasks run in."
  value       = one(module.network[*].subnet_ids)
}

output "app_security_group_id" {
  description = "Security group id for the app tasks."
  value       = one(module.network[*].app_sg_id)
}

output "api_task_definition_arn" {
  description = "api task definition ARN (reused with a command override to run migrations)."
  value       = one(module.compute[*].api_task_definition_arn)
}

output "ui_bucket_name" {
  description = "S3 bucket the UI build (ui/dist) is synced to."
  value       = one(module.ui[*].bucket_name)
}

output "ui_cloudfront_domain_name" {
  description = "CloudFront domain the UI is served from. Open https://<this>."
  value       = one(module.ui[*].cloudfront_domain_name)
}

output "ui_cloudfront_distribution_id" {
  description = "CloudFront distribution id, invalidated after every UI deploy."
  value       = one(module.ui[*].cloudfront_distribution_id)
}