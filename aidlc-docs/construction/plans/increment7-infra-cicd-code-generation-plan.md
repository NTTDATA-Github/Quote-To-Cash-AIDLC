# Increment 7 — Deployment Infrastructure (Terraform + AWS) + CI/CD (GitHub Actions)

**AI-DLC phase**: Construction → Code Generation (Part 1: Planning).
**Infrastructure Design**: reused as-is from
`aidlc-docs/construction/target-arch/infrastructure-design/{infrastructure-design,deployment-architecture}.md`
(service→resource mapping, Terraform layout, floci↔AWS parity, SECURITY/RESILIENCY
baselines). This plan turns that design into real on-disk Terraform, container images, and
GitHub Actions pipelines. It completes the still-open Phase 3 items **F (packaging), G
(Terraform), H (runbook), I (verification)** and adds a new **J (CI/CD)** dimension.

Nothing in this file is generated until the GATE below is approved. Each item has a
checkbox and a concrete "done when" so progress is trackable the same way prior increments
were.

---

## 0. What already exists (do not re-create)
- **App**: modular monolith, two hosts — `api` (FastAPI GraphQL + webhooks, `src/api/app.py`)
  and `worker` (consumers + outbox relay + reconcile scheduler, `src/worker/main.py`).
- **Profiles**: `APP_PROFILE=memory|postgres`; AWS services reached via `boto3` +
  `AWS_ENDPOINT_URL` (floci locally, real AWS in prod). Application code is identical
  local↔cloud — only endpoints/credentials/toggles differ.
- **Backing services (local)**: `docker-compose.yml` already runs postgres, floci
  (SNS/SQS/Secrets/Cognito), odoo, adminer. **No `app`/`worker` services, no Dockerfiles.**
- **Scripts**: `scripts/messaging_bootstrap.py` (topic + 4 FIFO queues + DLQs),
  `scripts/seed_cognito.py`, `scripts/seed_demo.py`, `scripts/local.sh`, `scripts/install-hooks.sh`.
- **Migrations**: Alembic (`alembic upgrade head`), migrations `0001`–`0007`.
- **Quality gates** (steering `quality-gates`): `ruff format --check`, `ruff check`,
  `lint-imports` (0 broken), `pytest` (`APP_PROFILE=memory`), `npm --prefix ui run build`.

## 0b. Target topology to provision (from the Infrastructure Design — unchanged)
VPC + private subnets → **Aurora Serverless v2 Postgres**, **ECS Fargate** `api` (behind
**ALB** :443) and `worker`, **SNS FIFO** `platform-domain-events.fifo` → **SQS FIFO ×4 +
DLQ ×4** (`order-processing`, `order-delivery`, `projections`, `webhook-dispatch`),
**Secrets Manager + KMS**, **Cognito** (reseller + operator pools), **EventBridge
Scheduler** (reconcile), **ECR**, **CloudWatch Logs**, least-privilege **IAM** task roles,
**VPC endpoints** for SNS/SQS/Secrets.

---

## GATE — decisions to confirm before code generation
Recommended defaults in **bold**. Answer per question, or just say "all recommended".

**Q1. How should GitHub Actions authenticate to AWS?**
- **A. GitHub OIDC → short-lived IAM role (no stored AWS keys)** ← recommended
- B. Long-lived IAM access key/secret stored in GitHub Secrets
- C. Other / you'll tell me

**Q2. Where does Terraform state live?**
- **A. S3 state bucket + DynamoDB lock table, one bootstrap config applied once** ← recommended
- B. Terraform Cloud / HCP
- C. Local state only (single operator, not for a team)

**Q3. How many AWS environments now?**
- **A. `staging` + `prod` (separate state keys + tfvars); local stays floci** ← recommended
- B. `prod` only for now (add staging later)
- C. More (dev/staging/prod) — name them

**Q4. Deploy trigger / promotion model?**
- **A. PR → CI + `terraform plan` (comment); merge to `main` → auto-deploy staging;
  prod via manual approval (GitHub Environment protection)** ← recommended
- B. Deploy on git tag / GitHub Release only
- C. Manual `workflow_dispatch` for every deploy

**Q5. How do images reach ECS on deploy?**
- **A. CI builds+pushes `api`/`worker` images to ECR tagged with the commit SHA;
  Terraform sets the task-def image to that tag; `terraform apply` rolls the service** ← recommended
- B. Push `:latest` + `aws ecs update-service --force-new-deployment` (no TF image change)

**Q6. When do DB migrations run in the pipeline?**
- **A. A one-off ECS `run-task` (`alembic upgrade head`) after infra apply, before the
  service rolls** ← recommended
- B. A CI job that connects to the DB directly (requires CI network reach into the VPC)
- C. Manual step in the runbook, not automated yet

**Q7. Confirm the three open infra decisions from the design (O-INFRA-1/2/3):**
- **A. Aurora Serverless v2 + ALB + Cognito-on-AWS-only (local stays JWT/header stub)** ← recommended (design defaults)
- B. I want to change one of these (say which)

**Q8. Extensions for this increment (inherited):** Security Baseline **Yes**, Resiliency
Baseline **Yes**, Property-Based Testing **N/A** (infra/pipeline code, no pure functions).
Confirm or adjust.

---

## F. Packaging (containerize the two hosts)
- [ ] `Dockerfile.api` — pinned `python:3.11-slim`, non-root user, install from
  `pyproject.toml` (no `latest`), `CMD` runs uvicorn on `src.api.app:app`.
- [ ] `Dockerfile.worker` — same base/deps, `CMD` runs `python -m src.worker.main`.
- [ ] `.dockerignore` (exclude `.venv`, `ui/node_modules`, caches, `aidlc-docs`, `.git`).
- [ ] Add `app` + `worker` services to `docker-compose.yml` (env: `DATABASE_URL`,
  `AWS_ENDPOINT_URL`, `APP_PROFILE=postgres`, `ERP_ODOO_MODE`) so the full stack runs via compose.
- **Done when**: `docker compose build` succeeds and `docker compose up` brings api+worker
  up healthy against local postgres+floci.

## G. Terraform (`infra/terraform/`)
Layout exactly as the Infrastructure Design fixes it:
- [ ] `providers.tf` — AWS provider; `endpoints{}` + dummy creds when `use_floci=true`.
- [ ] `variables.tf` — `use_floci`, `region`, `environment`, `image_tag`, `db_password`,
  `odoo_secret`, sizing knobs.
- [ ] `messaging.tf` — SNS FIFO topic + SQS FIFO ×4 + DLQ ×4 + subscriptions
  (`raw_message_delivery=true`, `filter_policy` on `eventType`) + queue policies.
  **Must match `messaging-topology.md` exactly.** (floci + AWS)
- [ ] `secrets.tf` — Secrets Manager secrets + versions (Odoo creds, webhook keys). (floci + AWS)
- [ ] `data_aws.tf` — `count = var.use_floci ? 0 : 1`: VPC + private subnets + SGs + VPC
  endpoints, Aurora Serverless v2, ECS cluster/services/task-defs (api+worker), ALB +
  target groups + :443 listener, Cognito user pools + app clients, IAM least-privilege
  task roles (no wildcards), ECR repos, CloudWatch log groups, EventBridge Scheduler.
- [ ] `outputs.tf` — topic ARN, queue URLs, secret ARNs, DB endpoint, ALB DNS, ECR URLs.
- [ ] `envs/local.tfvars` (`use_floci=true`, `http://localhost:4566`),
  `envs/staging.tfvars`, `envs/prod.tfvars` (per Q3).
- [ ] (Per Q2) `infra/terraform/bootstrap/` — S3 state bucket + DynamoDB lock table +
  `backend.tf` partial config wired into the root.
- **Done when**: `terraform init` + `terraform validate` pass for every env, and
  `terraform plan -var-file=envs/local.tfvars` is clean against floci.
- **Security (SECURITY baseline, blocking)**: secrets only via `TF_VAR_*` / Secrets
  Manager (never committed to tfvars); IAM task roles scoped (api: read config + publish
  SNS + read secrets; worker: consume SQS + write DB + read secrets); Aurora + Fargate in
  private subnets; ALB the only public ingress; KMS at rest; TLS in transit.

## J. CI/CD (GitHub Actions, `.github/workflows/`)
- [ ] `ci.yml` — on PR + push to `main`. Jobs: **quality gates** = `ruff format --check`,
  `ruff check`, `lint-imports`, `pytest` (`APP_PROFILE=memory`), and `ui-build`
  (`npm --prefix ui ci && npm --prefix ui run build`). Mirrors the pre-commit hook + the
  `quality-gates` steering so CI is the same gate, enforced server-side.
- [ ] `terraform-plan.yml` — on PR touching `infra/**`: `fmt -check`, `init`, `validate`,
  `plan`, post the plan as a PR comment. Auth per Q1; state per Q2.
- [ ] `build-images.yml` (or a job in deploy) — build `Dockerfile.api`/`Dockerfile.worker`,
  push to ECR tagged with the commit SHA (per Q5).
- [ ] `deploy.yml` — promotion per Q4: build+push images → `terraform apply` for the env
  → run migrations per Q6 → roll ECS services. Prod gated by a GitHub **Environment**
  protection rule (manual approval).
- [ ] Document required GitHub repo config: the OIDC IAM role ARN, `AWS_REGION`, and
  per-environment secrets; `environment:` protection on `prod`.
- **Done when**: `ci.yml` is green on a PR; `terraform-plan.yml` comments a plan;
  `deploy.yml` dry-runs/validates (full apply runs in your AWS account, not the sandbox).

## H. Runbook + docs
- [ ] `docs/e2e-runbook.md` — local bring-up (compose → `terraform … local.tfvars` →
  `alembic upgrade head` → `seed_demo` → api/worker → Odoo Automation Rule → place order →
  observe status).
- [ ] `docs/deploy-aws.md` — one-time bootstrap (state backend, OIDC role, ECR), then the
  per-environment deploy flow and how promotion/approval works.
- [ ] Update `docs/local-setup.md` to point at the runbook; add an ADR for the CI/CD +
  state-backend + OIDC decisions.

## I. Verification
- [ ] `terraform validate` + `plan` against floci (local) runnable here; AWS `apply`
  documented for your account (needs real AWS creds + network, out of sandbox scope).
- [ ] CI workflow validated (lint/test/ui gates run green).
- [ ] Manual AWS E2E checklist in `docs/deploy-aws.md` for a real account.

## Notes / honest constraints
- This sandbox has no `terraform` binary, no real AWS, and limited network. So G/J are
  authored + `terraform validate`/`actionlint`-checked and plan-tested against floci where
  possible; a real `apply` to AWS and a live pipeline run happen in your environment per
  `docs/deploy-aws.md`. This will be stated explicitly, not glossed, in the Build-and-Test
  summary (same honesty bar as prior increments).
- No change to application code is required by this increment; if running the containers
  surfaces a real app bug (as happened in Phase 3 items B/C), it will be fixed and recorded.

## Build-and-Test (after code generation)
Run and record: `ruff format --check`, `ruff check` (All checks passed), `lint-imports`
(0 broken), `pytest` (`APP_PROFILE=memory`), `npm --prefix ui run build`, `terraform fmt
-check` + `validate`, and `actionlint` on the workflows. Record results in
`aidlc-docs/aidlc-state.md` per the quality-gates steering.
