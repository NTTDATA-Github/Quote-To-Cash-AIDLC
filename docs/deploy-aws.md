# Deploying to AWS (Terraform + GitHub Actions)

One AWS environment, named `staging`. It is intentionally **public** for easy debugging
(see the warning below). Infrastructure is Terraform; CI/CD is GitHub Actions over OIDC
(no stored AWS keys). Decisions are recorded in
[ADR-0020](adr/0020-terraform-aws-deploy-and-cicd.md).

> ⚠️ **Public environment.** `envs/staging.tfvars` sets `public_access = true`, which makes
> Aurora internet-reachable and gives the Fargate tasks public IPs. This is a debug
> convenience and is **not safe for real data** — it exposes a multi-tenant database to the
> internet behind only a password. Keep real customer data out of this environment. To lock
> it down, set `public_access = false` and redeploy (the DB + tasks go private, the ALB
> stays the only public ingress, and you reach the DB via ECS Exec or an SSM tunnel —
> see "Debugging" below). "Public" is network reachability only; Cognito, the DB password,
> and Secrets Manager are always on.

## One-time account bootstrap

### 1. Remote state (S3 + DynamoDB)
```bash
cd infra/terraform/bootstrap
terraform init
terraform apply -var="state_bucket=<your-globally-unique-bucket>"
```
Note the `state_bucket` + `lock_table` outputs. Put the bucket name into
`infra/terraform/envs/staging.s3.tfbackend` (or pass it via `-backend-config` as the
workflows do).

### 2. GitHub OIDC deploy role
Set `github_oidc_repo = "owner/repo"` in `envs/staging.tfvars`, then after the first apply
(below) read the role ARN from `terraform output github_deploy_role_arn`. The role trusts
only this repo (via the OIDC `sub` condition) and needs no stored keys.

### 3. GitHub repo configuration
Add these to the repo (Settings → Secrets and variables → Actions), and create an
Environment named `staging` (optionally with a required-reviewer protection rule to gate
each deploy):

| Kind | Name | Value |
|---|---|---|
| Secret | `AWS_DEPLOY_ROLE_ARN` | the `github_deploy_role_arn` output |
| Secret | `TF_STATE_BUCKET` | the bootstrap state bucket |
| Secret | `DB_PASSWORD` | the Aurora master password (`TF_VAR_db_password`) |
| Variable | `AWS_REGION` | e.g. `us-east-1` |

## First deploy (from your machine)
```bash
cd infra/terraform
export TF_VAR_db_password='<a strong password>'
terraform init -backend-config=envs/staging.s3.tfbackend
terraform apply -var-file=envs/staging.tfvars \
  -var="api_image=<ECR>/o2c/api:bootstrap" \
  -var="worker_image=<ECR>/o2c/worker:bootstrap"
```
The ECR repositories are created by this apply, so the very first run can use any
placeholder image tag; the first real images arrive via the deploy workflow. Then run the
migration once (`alembic upgrade head`) — either the workflow step does it, or run it
manually as an ECS task.

## Ongoing: the pipelines
- **`ci.yml`** — on every PR + push to `main`: ruff (changed files), import-linter, pytest
  (`APP_PROFILE=memory`), UI build. Same gates as the pre-commit hook.
- **`terraform-plan.yml`** — on PRs touching `infra/terraform/**`: `fmt`, `validate`,
  `plan`, posted as a PR comment.
- **`deploy.yml`** — on push to `main` (or manual `workflow_dispatch`): builds + pushes the
  `api`/`worker` images to ECR tagged with the commit SHA, `terraform apply` (which points
  the task defs at the new images and rolls the services), runs the Alembic migration as a
  one-off ECS task, and waits for the services to stabilize. Gate it with the `staging`
  Environment's protection rule if you want manual approval before each deploy.

## Debugging

### App URL
`terraform output alb_dns_name` → the ALB. Cert-less by default, so it serves plain HTTP
on `:80`. Set `acm_certificate_arn` in the tfvars to switch to HTTPS (`:80` then redirects
to `:443`).

### Logs
```bash
aws logs tail /ecs/o2c-staging/api --follow
aws logs tail /ecs/o2c-staging/worker --follow
```

### Into the database
With `public_access = true` you can point any client straight at
`terraform output aurora_endpoint` on `:5432` (user/password from the tfvars/TF_VAR).

With `public_access = false`, the DB is private — use either:
- **ECS Exec** (no extra infra), open a shell in a running task and query from there:
  ```bash
  aws ecs execute-command --cluster o2c-staging \
    --task <task-id> --container api --interactive --command "/bin/bash"
  ```
- **SSM port-forward** through an SSM-managed jump instance to get `localhost:5432` on your
  laptop (requires adding a small jump instance — not provisioned by default).

## What was NOT verified in the authoring environment
The authoring sandbox has no `terraform` binary, no AWS account, and limited network, so a
real `terraform apply` to AWS and a live pipeline run were **not** executed there. The
Terraform is structured and `fmt`/`validate`-oriented; the local floci path (`use_floci=true`)
is the runnable slice. Run the steps above in your own AWS account to complete verification.
