# Root composition. Messaging + secrets always run (floci + AWS). The AWS-only modules are
# gated with count = local.aws_count (0 when use_floci=true), so the local floci path
# provisions only what floci emulates.

data "aws_caller_identity" "current" {
  count = local.aws_count
}

module "messaging" {
  source            = "./modules/messaging"
  topic_name        = local.topic_name
  queue_filters     = local.queue_filters
  max_receive_count = local.max_receive_count
}

module "secrets" {
  source            = "./modules/secrets"
  prefix            = local.prefix
  odoo_secret_value = var.odoo_secret_value
}

module "network" {
  source        = "./modules/network"
  count         = local.aws_count
  prefix        = local.prefix
  vpc_cidr      = var.vpc_cidr
  public_access = var.public_access
}

module "database" {
  source        = "./modules/database"
  count         = local.aws_count
  prefix        = local.prefix
  subnet_ids    = module.network[0].subnet_ids
  db_sg_id      = module.network[0].db_sg_id
  db_name       = var.db_name
  db_username   = var.db_username
  db_password   = var.db_password
  min_acu       = var.aurora_min_acu
  max_acu       = var.aurora_max_acu
  public_access = var.public_access
}

module "registry" {
  source      = "./modules/registry"
  count       = local.aws_count
  name_prefix = var.name_prefix
}

module "identity" {
  source = "./modules/identity"
  count  = local.aws_count
  prefix = local.prefix
}

module "observability" {
  source = "./modules/observability"
  count  = local.aws_count
  prefix = local.prefix
}

module "iam" {
  source           = "./modules/iam"
  count            = local.aws_count
  prefix           = local.prefix
  topic_arn        = module.messaging.topic_arn
  work_queue_arns  = module.messaging.work_queue_arns
  dlq_arns         = module.messaging.dlq_arns
  secret_arn_glob  = local.secret_arn_glob
  github_oidc_repo = var.github_oidc_repo
}

module "compute" {
  source               = "./modules/compute"
  count                = local.aws_count
  prefix               = local.prefix
  region               = var.region
  vpc_id               = module.network[0].vpc_id
  subnet_ids           = module.network[0].subnet_ids
  app_sg_id            = module.network[0].app_sg_id
  alb_sg_id            = module.network[0].alb_sg_id
  api_image            = var.api_image
  worker_image         = var.worker_image
  api_desired_count    = var.api_desired_count
  worker_desired_count = var.worker_desired_count
  task_cpu             = var.task_cpu
  task_memory          = var.task_memory
  execution_role_arn   = module.iam[0].task_execution_role_arn
  api_task_role_arn    = module.iam[0].api_task_role_arn
  worker_task_role_arn = module.iam[0].worker_task_role_arn
  api_log_group        = module.observability[0].api_log_group
  worker_log_group     = module.observability[0].worker_log_group
  app_env              = local.app_env
  acm_certificate_arn  = var.acm_certificate_arn
}

module "odoo" {
  source              = "./modules/odoo"
  count               = local.aws_count
  prefix              = local.prefix
  region              = var.region
  vpc_id              = module.network[0].vpc_id
  subnet_ids          = module.network[0].subnet_ids
  execution_role_arn  = module.iam[0].task_execution_role_arn
  execution_role_name = module.iam[0].task_execution_role_name
  odoo_image          = var.odoo_image != "" ? var.odoo_image : "${module.registry[0].odoo_repository_url}:bootstrap"
  odoo_db_password    = var.odoo_db_password
}
