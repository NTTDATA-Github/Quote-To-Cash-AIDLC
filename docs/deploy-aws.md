# Deploying to AWS (Terraform + GitHub Actions)

One AWS environment, named `staging`. It is intentionally **public** for easy debugging
(see the warning below). Infrastructure is Terraform; CI/CD is GitHub Actions over OIDC
(no stored AWS keys). Decisions are recorded in
[ADR-0020](adr/0020-terraform-aws-deploy-and-cicd.md).

> ⚠️ **Public environment.** `envs/staging.tfvars` sets `public_access = true`, which makes
> Aurora internet-reachable and gives the Fargate tasks public IPs. This is a debug
> convenience and is **not safe for real data** — it exposes a multi-tenant database to the
> internet behind only a password. Keep real customer data out of this environment.
> "Public" is network reachability only; Cognito, the DB password, and Secrets Manager are
> always on.
>
> **`public_access = false` does not fully lock this down yet.** It removes the `0.0.0.0/0`
> security-group rules on the DB/app ports, but `modules/compute` and `modules/odoo` always
> set `assign_public_ip = true` on the Fargate tasks regardless of the flag, and there is no
> NAT gateway or VPC endpoints — a private subnet doesn't exist, so a task with no public IP
> would have no route to pull its image or reach AWS services at all. Making `public_access`
> a real lever needs private subnets + NAT (or VPC endpoints for ECR/Secrets
> Manager/CloudWatch Logs) wired through `modules/network`, `modules/compute`, and
> `modules/odoo` together — not done here. Track this as a prerequisite before onboarding
> real customer data (see ADR-0020's "Revisit when").

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
this repo (any branch/workflow — the OIDC `sub` condition is `repo:<owner>/<repo>:*`) and
needs no stored keys. It's granted `AdministratorAccess` because the apply it runs touches
every module in this config, not just ECS/ECR — see the note on this in `modules/iam/main.tf`
and ADR-0020.

This is the one step in this whole runbook that **must** be run by a human from their own
AWS credentials, and it's inherent to OIDC trust roles: GitHub can't create the role that
lets GitHub in. Everything after this step is automated by `deploy.yml`.

### 3. GitHub repo configuration
Add these to the repo (Settings → Secrets and variables → Actions), and create an
Environment named `staging` (optionally with a required-reviewer protection rule to gate
each deploy):

| Kind | Name | Value |
|---|---|---|
| Secret | `AWS_DEPLOY_ROLE_ARN` | the `github_deploy_role_arn` output |
| Secret | `DB_PASSWORD` | the Aurora master password (`TF_VAR_db_password`) |
| Secret | `ODOO_DB_PASSWORD` | the Odoo Postgres password (`TF_VAR_odoo_db_password`). Different from `DB_PASSWORD`. |
| Variable | `AWS_REGION` | e.g. `us-east-1` |

## First deploy (from your machine, once)
This is the apply that creates the OIDC role from step 2 above — so it has to run with
your own AWS credentials, before CI can do anything. It also creates everything else
(VPC, Aurora, ECR, Cognito, the UI's S3+CloudFront, ...): it's the whole stack, in one shot.
```bash
cd infra/terraform
export TF_VAR_db_password='<a strong password>'
export TF_VAR_odoo_db_password='<a different strong password>'
terraform init -backend-config=envs/staging.s3.tfbackend
terraform apply -var-file=envs/staging.tfvars
```
Set both passwords on this first apply — later applies leave them alone, but an empty
password on the first apply is stored and will not be filled in afterward. Leave
`api_image`/`worker_image`/`odoo_image` unset; they fall back to `<repo>:bootstrap`, which
doesn't exist yet, so the api/worker/Odoo services will sit unhealthy until the next step.
That's expected — don't `docker push` anything by hand here.

Now add the GitHub secrets (step 3) and run the **Deploy** workflow once manually
(Actions → Deploy (staging) → Run workflow, with `rebuild_odoo` checked — it's the only way
Odoo's image gets pushed the first time, since the push-triggered path only rebuilds Odoo
when `Dockerfile.odoo` changes). It builds and pushes real api/worker/Odoo images, re-applies
with those images, runs the portal's Alembic migration, and deploys the UI. After that,
every push to `main` deploys the same way automatically.

## Ongoing: the pipelines
- **`ci.yml`** — on every PR + push to `main`: ruff (changed files), import-linter, pytest
  (`APP_PROFILE=memory`), UI build. Same gates as the pre-commit hook.
- **`terraform-plan.yml`** — on PRs touching `infra/terraform/**`: `fmt`, `validate`,
  `plan`, posted as a PR comment.
- **`deploy.yml`** — on push to `main` (or manual `workflow_dispatch`): ensures the ECR
  repos exist, builds + pushes the `api`/`worker` images tagged with the commit SHA (and
  Odoo's, only if `Dockerfile.odoo`/`infra/terraform/modules/odoo` changed or
  `rebuild_odoo` was checked on a manual run), `terraform apply` (points the task defs at
  the new images and rolls the services), runs the Alembic migration as a one-off ECS
  task, waits for services to stabilize, then builds the UI with the live AWS endpoints
  baked in and syncs it to S3 + invalidates CloudFront. Gate it with the `staging`
  Environment's protection rule if you want manual approval before each deploy.

## Odoo

Odoo is a second service in the same VPC. Its database is a private RDS Postgres 15.
The portal stays on Aurora. Do not point Odoo at Aurora.

People open Odoo at `http://<terraform output odoo_alb_dns_name>`. The worker reaches
that same address. The RDS host (`odoo_db_endpoint`) accepts connections only from
the Odoo task.

The image is `Dockerfile.odoo`. On an empty database it installs Sales, Inventory,
and Invoicing, then grants those rights to internal users. Login is `admin` / `admin`.
Change that password before anyone else uses it. Attachments live on the task disk
and are gone when the task is replaced; the database is not.

`erp_adapter_mode` stays `stub` until Odoo answers. Then set it to `real` in
`envs/staging.tfvars`, create an ERP connection whose base URL is the Odoo load
balancer (`http://<odoo_alb_dns_name>`, database `odoo`, user `admin`), and apply
again. A cloud Odoo cannot call `127.0.0.1`. The worker's poll is what picks up
orders. Bedrock and the code-generation service are a separate setup; they are
not required for Odoo to come up.

### Building and pushing Odoo's image
Normally you never do this by hand — the Deploy workflow does it, only when
`Dockerfile.odoo`/`infra/terraform/modules/odoo` changed, or when you tick `rebuild_odoo`
on a manual run (Actions → Deploy (staging) → Run workflow). Odoo's ECS cluster is
**`o2c-staging-odoo`**, not the main `o2c-staging` app cluster — it's a separate cluster
from api/worker (`modules/odoo/main.tf`). If you ever do need to force a redeploy by hand:
```bash
aws ecs update-service --cluster o2c-staging-odoo --service o2c-staging-odoo --force-new-deployment
```
The first Odoo boot can take several minutes. Follow it with
`aws logs tail /ecs/o2c-staging/odoo --follow`. The site is up when `/web/login`
returns 200.

## UI

A separate S3 bucket + CloudFront distribution (`modules/ui`) serves the built React app
(`ui/dist`). `terraform output ui_cloudfront_domain_name` is the URL — open
`https://<that>`. The Deploy workflow builds the UI after `terraform apply` (so it can bake
the real ALB/Cognito endpoints into the build via Vite env vars — see `ui/vite.config.ts`),
syncs `ui/dist` to the bucket, and invalidates the CloudFront cache. There's no manual step.

The ALB is plain HTTP (cert-less by default), but CloudFront is always HTTPS, so a browser
on the UI page can't call the ALB directly (mixed content). `modules/ui` routes `/graphql*`
through the same CloudFront distribution to the ALB as a second origin instead — same
origin as the UI, so `cors_allowed_origins` doesn't need to list the UI's URL, and there's
no HTTP/HTTPS mismatch. It stays `"*"` by default only as a fallback for anything calling
the api directly (not through CloudFront).

**Known gap:** CloudFront's SPA fallback (403/404 → `index.html`, for React Router routes)
is distribution-wide, so an API 403/404 — not a GraphQL error payload, an actual HTTP
403/404, e.g. a rejected JWT — also gets rewritten to `index.html` with a 200. The UI will
show a confusing parse error instead of "unauthorized" in that case. Scoping the SPA
fallback to only the S3 behavior needs a CloudFront Function, which wasn't added — this is
a staging environment and the failure mode is a bad error message, not a security issue.

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

## What's actually been verified
`terraform init` (against the real `staging` S3/DynamoDB backend), `validate`, and `plan`
have been run against this account — `plan` is clean (resources to add, zero conflicts,
no orphans from an earlier interrupted run). **A real `terraform apply` and a live
`deploy.yml` run have not been executed yet** — that first apply (see "First deploy" above)
is still the next step, and it's the one thing in this whole runbook that costs real money
(Aurora, two ALBs, Fargate, RDS) and can't be dry-run. The local floci path
(`use_floci=true`) is a separate, fully runnable slice that needs none of this.
