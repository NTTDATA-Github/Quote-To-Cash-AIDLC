#!/bin/bash
# One-time bootstrap AFTER infra/terraform/bootstrap has been applied: brings up staging
# (ECR, VPC, Aurora, IAM OIDC role, ...) with placeholder images, then wires the GitHub
# Actions deploy pipeline with the secrets it needs (AWS_DEPLOY_ROLE_ARN, TF_STATE_BUCKET,
# DB_PASSWORD, ODOO_DB_PASSWORD). Safe to re-run: terraform and `gh secret set` are both
# idempotent, and passwords are reused from .local/staging-secrets.env if already generated.
#
# Requires: terraform, aws CLI creds, and `gh auth login` already done.
# Usage: scripts/deploy-bootstrap.sh [extra terraform apply args, e.g. -auto-approve]
set -euo pipefail
cd "$(dirname "$0")/../infra/terraform"

SECRETS_FILE="../../.local/staging-secrets.env"
mkdir -p "$(dirname "$SECRETS_FILE")"

if [[ -f "$SECRETS_FILE" ]]; then
  source "$SECRETS_FILE"
else
  DB_PASSWORD=$(LC_ALL=C openssl rand -base64 32 | tr -dc 'A-Za-z0-9')
  ODOO_DB_PASSWORD=$(LC_ALL=C openssl rand -base64 32 | tr -dc 'A-Za-z0-9')
  cat > "$SECRETS_FILE" <<EOF
DB_PASSWORD=$DB_PASSWORD
ODOO_DB_PASSWORD=$ODOO_DB_PASSWORD
EOF
  chmod 600 "$SECRETS_FILE"
fi
# Guard: RDS requires 8-128 chars; a mangled `openssl`/`tr` would otherwise silently
# produce a short or empty password that only fails later, deep inside `terraform apply`.
[[ ${#DB_PASSWORD} -ge 16 && ${#ODOO_DB_PASSWORD} -ge 16 ]] || { echo "generated password too short" >&2; exit 1; }
export TF_VAR_db_password="$DB_PASSWORD"
export TF_VAR_odoo_db_password="$ODOO_DB_PASSWORD"

echo "==> terraform init"
terraform init -backend-config=envs/staging.s3.tfbackend

echo "==> terraform apply (placeholder images)"
terraform apply -var-file=envs/staging.tfvars \
  -var="api_image=placeholder" \
  -var="worker_image=placeholder" \
  -var="odoo_image=placeholder" \
  "$@"

ROLE_ARN=$(terraform output -raw github_deploy_role_arn)
STATE_BUCKET=$(grep '^bucket' envs/staging.s3.tfbackend | sed -E 's/.*"(.*)".*/\1/')
[[ "$ROLE_ARN" == arn:aws:iam::*:role/* ]] || { echo "github_deploy_role_arn output looks wrong: '$ROLE_ARN'" >&2; exit 1; }
[[ -n "$STATE_BUCKET" ]] || { echo "could not parse bucket from envs/staging.s3.tfbackend" >&2; exit 1; }

echo "==> pushing GitHub Actions secrets"
gh secret set AWS_DEPLOY_ROLE_ARN --body "$ROLE_ARN"
gh secret set TF_STATE_BUCKET     --body "$STATE_BUCKET"
gh secret set DB_PASSWORD         --body "$DB_PASSWORD"
gh secret set ODOO_DB_PASSWORD    --body "$ODOO_DB_PASSWORD"

echo
echo "Done. Passwords saved in $SECRETS_FILE (gitignored)."
echo "Commit Dockerfile.odoo + modules/odoo + envs/staging.tfvars, then push to main"
echo "(or: gh workflow run deploy.yml) to let the pipeline build real images and deploy."
