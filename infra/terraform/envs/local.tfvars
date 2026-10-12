# Local development against floci. Provisions ONLY what floci emulates (SNS/SQS/Secrets).
# Everything AWS-only (VPC/Aurora/ECS/ALB/Cognito/IAM/ECR) is count-gated off.
# Init with a local state file (no remote backend for throwaway local state):
#   terraform -chdir=infra/terraform init -backend=false
#   terraform -chdir=infra/terraform apply -var-file=envs/local.tfvars
use_floci      = true
floci_endpoint = "http://localhost:4566"
environment    = "local"
region         = "us-east-1"
