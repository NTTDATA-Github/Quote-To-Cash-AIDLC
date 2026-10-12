# The single AWS environment (named `staging` — it is intentionally public and debug-
# friendly, so "staging" is the honest label, not "prod").
use_floci   = false
environment = "staging"
region      = "us-east-1"

# PUBLIC-everything, as requested: Aurora is internet-accessible and Fargate tasks get
# public IPs with 0.0.0.0/0 ingress on the app/db ports. Convenient for debugging, NOT
# safe for real data. Flip to false to lock the environment down (ALB stays the only
# public ingress; reach the DB via ECS Exec / SSM tunnel instead — see docs/deploy-aws.md).
public_access = true

# Sizing
aurora_min_acu       = 0.5
aurora_max_acu       = 4
api_desired_count    = 1
worker_desired_count = 1

# ERP dispatch: "stub" until Odoo is up and the connection points at it.
# Then set this to "real" and apply again.
erp_adapter_mode = "stub"

# Odoo image and its RDS password are NOT stored here.
#   export TF_VAR_odoo_db_password='...'
#   -var="odoo_image=<ECR>/o2c/odoo:<tag>"   (optional; default is :bootstrap)

# UI origin(s). Set to the deployed UI URL; "*" is permissive for early debugging.
cors_allowed_origins = "*"

# Set to "owner/repo" to create the GitHub Actions OIDC deploy role (recommended).
github_oidc_repo = "sridarsaikrishnan/AI-DLC-ERP-Supply-Chain-Order-Portal"

# Supply these at apply time via environment, NEVER in this file:
#   export TF_VAR_db_password=...            (Aurora master password)
#   export TF_VAR_odoo_secret_value='{...}'  (optional; placeholder used if unset)
#   api_image / worker_image are set by the deploy workflow to the commit-SHA ECR tag.
# acm_certificate_arn is empty => ALB serves plain HTTP on :80 (cert-less staging).
