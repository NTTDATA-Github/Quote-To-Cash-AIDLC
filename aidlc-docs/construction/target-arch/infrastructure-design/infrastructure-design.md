# Infrastructure Design — Target Architecture (Phase 3: full E2E)

Maps the logical components (from `application-design/target-architecture.md` and
`messaging-topology.md`) to real infrastructure, provisioned by **Terraform**, runnable
locally on **floci** and deployable to **AWS**. Prior decisions are inherited (single
Postgres, ES on Order, SNS FIFO→SQS FIFO, Cognito, Secrets Manager, ECS Fargate); this
doc fixes the concrete resources and the local↔cloud parity.

**Updated for Increment 7-continued's module refactor + the UI/CI-CD/Odoo infra that
followed it** — see "Revision history" at the bottom.

## Service → infrastructure mapping
| Logical component | AWS resource | Local (floci/compose) |
|---|---|---|
| `api` host (GraphQL + webhooks) | ECS Fargate service behind ALB | container / uvicorn |
| `worker` host (consumers + relay + scheduler) | ECS Fargate service | container / process |
| Event store + outbox + projections + config | Aurora Serverless v2 PostgreSQL | `postgres:16` container |
| Domain event topic | SNS FIFO `platform-domain-events.fifo` | floci SNS |
| Work queues + DLQs | SQS FIFO ×5 (+5 DLQ) | floci SQS |
| Secrets (Odoo creds, webhook keys, Odoo DB password) | Secrets Manager | floci Secrets Manager |
| Identity | **One** Cognito user pool, role via `cognito:groups` (OPERATOR), tenant via `custom:tenant_id` | stub / floci (partial) |
| Scheduler (reconcile) | `worker`'s own in-process loop (`ReconcileScheduler`, `RECONCILE_INTERVAL_SECONDS`), not EventBridge | same loop |
| Observability | CloudWatch Logs (api/worker/odoo log groups, 30-day retention) | stdout + logs |
| ERP (Odoo) | **Second, isolated stack**: its own ECS cluster, Fargate task, ALB, and RDS Postgres 15 — see "Odoo: a parallel stack" below | `odoo:17` container |
| UI (React SPA) | S3 (private) + CloudFront (OAC), `/graphql*` routed to the api ALB as a second CloudFront origin | Vite dev server |
| Container registry | ECR ×3 (`api`, `worker`, `odoo`), immutable tags, scan-on-push, untagged-image expiry 14d | local image build |
| CI/CD | GitHub Actions over OIDC (no stored AWS keys) — see "CI/CD pipeline" below | n/a |
| Network | VPC, **public** subnets only (no NAT/private subnets yet), 3 security groups (alb/app/db) | compose network |

Two things that changed from the original plan and are now the actual, running design
(not aspirational): there is **one** Cognito pool, not two (reseller+operator share it,
distinguished by `cognito:groups`), and the reconcile scheduler is an in-process worker
loop, not EventBridge Scheduler — simpler to deploy, same effect for a single-replica
worker. Both are called out again in "Resolved decisions" below so they aren't mistaken
for drift.

## What floci provisions vs. what it can't
- **floci-emulated (Terraform, `-var use_floci=true`)**: SNS FIFO, SQS FIFO + DLQs, subscriptions + filter policies, Secrets Manager. This is everything the running app needs locally.
- **AWS-only (Terraform, real provider, `count = local.aws_count`)**: VPC/network, Aurora, ECS/Fargate (api+worker+odoo), ALB ×2, Cognito, IAM, ECR, CloudWatch, the UI's S3+CloudFront, Odoo's own RDS. Locally these are replaced by containers (Postgres, Odoo, the app/worker containers) and the Vite dev server — floci does not meaningfully emulate them.

## Terraform layout (as modularized, Increment 7-continued)
```
infra/terraform/
  bootstrap/              # ONE-TIME, per account, run with local state: S3 state bucket + DynamoDB lock table
  backend.tf              # s3 backend, partial config filled at `terraform init -backend-config=...`
  providers.tf            # aws provider; endpoints{} + dummy creds when use_floci=true
  versions.tf             # terraform/provider version pins
  variables.tf            # use_floci, region, public_access, db_password, odoo_*, github_oidc_repo, ...
  locals.tf               # prefix, messaging topology (mirrors scripts/messaging_bootstrap.py), app_env
  main.tf                 # root composition — wires every module below
  outputs.tf               # every id/url/arn the CI pipeline and the runbook need
  envs/
    local.tfvars           # use_floci=true
    staging.tfvars         # use_floci=false, public_access=true (debug-friendly, see Security)
    staging.s3.tfbackend    # bucket/key/region/dynamodb_table for `-backend-config`
  modules/
    messaging/              # SNS FIFO + SQS FIFO + DLQs            (floci + AWS)
    secrets/                 # Secrets Manager (Odoo connection)     (floci + AWS)
    network/                 # VPC, public subnets, 3 security groups        (AWS only)
    database/                 # Aurora Serverless v2 (the portal DB)          (AWS only)
    registry/                  # 3 ECR repos + lifecycle policies             (AWS only)
    identity/                   # 1 Cognito user pool + SPA client + OPERATOR group (AWS only)
    observability/               # CloudWatch log groups (api/worker)          (AWS only)
    iam/                           # task roles + GitHub OIDC deploy role        (AWS only)
    compute/                        # ECS cluster + api/worker services + ALB     (AWS only)
    odoo/                             # Odoo's own cluster+service+ALB+RDS         (AWS only)
    ui/                                # S3 + CloudFront for the React build         (AWS only)
```
The messaging/secrets modules are identical for floci and AWS (same AWS APIs, just a
different endpoint); every other module is gated at the root call site with
`count = local.aws_count` (0 when `use_floci=true`).

## One-time account bootstrap (must be run by a human)
GitHub can't create the IAM role that lets GitHub's CI assume a role in your account —
that's inherent to OIDC trust, not a gap to close. One human, once, with their own real
AWS credentials:
1. `infra/terraform/bootstrap` — local state, creates the S3 bucket + DynamoDB lock
   table the *main* config's remote state lives in.
2. The main config's **first** `terraform apply` (no CI yet) — creates everything,
   including the GitHub OIDC provider + deploy role (`modules/iam`). Both DB passwords
   (`TF_VAR_db_password`, `TF_VAR_odoo_db_password`) must be set on this specific apply —
   `lifecycle { ignore_changes = [password] }` on both databases means whatever is set
   here is permanent; an empty password here cannot be filled in later without
   recreating the database.
3. Add `AWS_DEPLOY_ROLE_ARN` / `DB_PASSWORD` / `ODOO_DB_PASSWORD` as GitHub secrets (+
   `AWS_REGION` as a variable) on a `staging` Environment. Every push to `main` after
   that deploys itself — see "CI/CD pipeline".

Full runbook: `docs/deploy-aws.md`.

## CI/CD pipeline (GitHub Actions, OIDC — no stored AWS keys)
- **`terraform-plan.yml`** — on any PR touching `infra/terraform/**`: `fmt -check`,
  `validate`, `plan`, posted as a PR comment. Read-only, no AWS mutation.
- **`deploy.yml`** — on push to `main` (or manual `workflow_dispatch` with
  `rebuild_odoo`), one job, in order:
  1. Assume the OIDC deploy role, `terraform init` against the real backend.
  2. `terraform apply -target=module.registry` first — guarantees the ECR repos exist
     before anything tries to `docker push` to them (makes a brand-new account
     self-sufficient; no human has to `apply` from a laptop before the first CI run).
  3. Build + push `api`/`worker` images, tagged with the commit SHA, every run.
  4. Build + push the **`odoo`** image only when `Dockerfile.odoo` or
     `infra/terraform/modules/odoo` changed (diffed against the previous commit), or
     `rebuild_odoo` was checked manually. Odoo's ECR repo is immutable-tagged and each
     new tag replaces the running task — rebuilding on every unrelated push would wipe
     Odoo's ephemeral attachment disk for no reason.
  5. Full `terraform apply` — rolls api/worker (and odoo, if rebuilt) onto the new
     image(s); re-passes Odoo's *currently-applied* image (read from state) when it
     wasn't rebuilt, so an unrelated deploy never resets it to the unpushed
     `:bootstrap` default.
  6. Runs the portal's Alembic migration as a one-off ECS task on the just-applied
     `api` task definition, waits for it to exit 0.
  7. Waits for the api/worker ECS services to stabilize.
  8. Builds the UI (`npm ci && npm run build`) **after** `terraform apply`, so the real
     ALB/Cognito endpoints (read via `terraform output`) get baked into the Vite build —
     Vite env vars are compile-time, not runtime.
  9. `aws s3 sync ui/dist` to the UI bucket + CloudFront invalidation.
- **`ci.yml`** (unchanged) — ruff, import-linter, pytest, UI build, on every PR/push.

## Odoo: a parallel stack, not a shared one
Odoo is **not** colocated with api/worker — its own ECS cluster (`o2c-staging-odoo`,
distinct from the app's `o2c-staging`), its own Fargate task (1024 CPU / 2048 MB — double
api/worker's size; Odoo is heavier and this is hardcoded in `modules/odoo`, not a
tfvars-tunable knob), its own ALB on port 80, and its own RDS Postgres 15 instance
(`db.t3.micro`, SSL forced off via a custom parameter group — Odoo's stock client doesn't
use RDS's default-on TLS). Reachable at `http://<odoo_alb_dns_name>`; its database is
reachable only from the Odoo task's security group — never from the portal's Aurora
network path, and never shared with it. `erp_adapter_mode` starts at `"stub"`; flipping it
to `"real"` and pointing a Connection at Odoo's ALB is a separate, later step, not part of
infra provisioning.

## UI hosting
Private S3 bucket (all public access blocked) behind CloudFront with Origin Access
Control (no public bucket, no public read — CloudFront is the only reader, enforced by a
bucket policy scoped to that one distribution's ARN). The ALB is plain HTTP by default
(cert-less staging, see Security); a browser on the HTTPS CloudFront page can't call an
HTTP origin directly (mixed content), so `/graphql*` is routed through the **same**
CloudFront distribution to the ALB as a second origin — same-origin from the browser's
perspective, which also means `cors_allowed_origins` never needs the UI's own URL. SPA
client-side routing (React Router) is handled by rewriting S3's 403/404 to `index.html`
with a 200 — distribution-wide, which means an actual API 403/404 (e.g. a rejected JWT)
also gets rewritten to a 200 `index.html` today; known, accepted gap (see Security).

## Messaging resources (must match messaging-topology.md)
- SNS FIFO topic `platform-domain-events.fifo` (`content_based_deduplication=false`).
- SQS FIFO: `order-processing.fifo`, `order-delivery.fifo`, `order-fulfillment.fifo`,
  `projections.fifo`, `webhook-dispatch.fifo` — each with a `-dlq.fifo` and
  `redrive_policy(maxReceiveCount=5)`.
- Subscriptions: topic→each queue, `raw_message_delivery=true`, `filter_policy` on
  `eventType` (scope `MessageAttributes`) per the topology table; `projections.fifo` has
  no filter (gets everything).
- Queue policy allowing SNS to `sqs:SendMessage`, scoped to this topic's ARN.

## Security (SECURITY baseline)
- Secrets in Secrets Manager (`secret_ref` only in DB, never the secret itself); Odoo's
  RDS password is also Secrets-Manager-held and injected into the ECS task via `secrets`
  (never an environment variable literal).
- IAM least-privilege task roles (api: read/write project secrets + ECS Exec channel;
  worker: consume SQS + publish SNS + read/write project secrets + ECS Exec channel; Odoo
  task: ECS Exec channel only). No wildcard resources except the two SSM-messaging
  actions, which AWS does not let you scope to a resource.
- **Deliberate, documented exception**: the GitHub Actions OIDC deploy role gets
  `AdministratorAccess`, not a scoped policy — its `terraform apply` touches every module
  in this config (VPC, RDS, IAM, Cognito, Secrets Manager, SNS/SQS, S3, CloudFront, ECR,
  ECS...), and a hand-picked set of FullAccess policies would silently miss the next
  module added. Trusted only to this one repo (`StringLike` on the OIDC `sub` claim,
  `repo:<owner>/<repo>:*` — any branch/workflow in the repo, no stored keys). Tighten
  under "Revisit when" below.
- **`public_access` (default `true` in `staging.tfvars`)**: Aurora gets `publicly_accessible=true` and both Aurora's and the app's security groups add `0.0.0.0/0` ingress
  on their DB/app ports. Deliberate debug convenience for a non-production environment —
  password-protected, but a publicly-reachable multi-tenant Postgres is one of the
  most-scanned things on the internet. "Public" is network reachability only — Cognito
  JWT auth, the DB password, and Secrets Manager are always on regardless of this flag.
- **Known gap, not yet closed**: flipping `public_access` to `false` removes the
  `0.0.0.0/0` security-group rules, but `modules/compute` and `modules/odoo` hardcode
  `assign_public_ip = true` on every Fargate task regardless of the flag — there is no
  NAT gateway or VPC endpoints, so a private subnet doesn't exist yet; a task with no
  public IP would have no route to pull its image or reach any AWS API. Making
  `public_access=false` a complete lock-down needs private subnets + NAT (or VPC
  endpoints for ECR/Secrets Manager/CloudWatch Logs) wired through `network`, `compute`,
  and `odoo` together. Tracked, not silently assumed done.
- Inbound ERP webhook auth: shared-secret-in-path for Odoo (Automation Rules can't HMAC a
  request) + HMAC for ERPNext-style ERPs; reconcile sweeper as the fallback either way.
- CloudFront's SPA 403/404→`index.html` rewrite (see "UI hosting") turns an unauthorized
  API response into a confusing 200 with a parse error instead of a clean "unauthorized" —
  a bad error message, not a security hole (the API still enforced the rejection; the UI
  just can't tell the user why). Fixing it scopes the rewrite with a CloudFront Function,
  not done yet.

## Sizing decisions (cost-conscious defaults, reviewed 2026-10-14)
Every tunable knob is already at AWS's practical floor for a working service — verified
against a real `terraform plan` (87 resources, 0 conflicts) against the live `staging`
backend:
- Aurora Serverless v2 `min_acu = 0.5` — the lowest floor AWS allows.
- api/worker Fargate: `512 CPU / 1024 MB` (0.5 vCPU / 1GB) — smallest valid combination.
- Odoo RDS: `db.t3.micro`, 20GB gp3 — cheapest Postgres instance class.
- No NAT gateway anywhere — usually the single biggest avoidable Fargate-adjacent cost
  (~$32/mo+); skipped entirely by using public subnets directly (see the `public_access`
  trade-off above).
- CloudFront `PriceClass_100` — cheapest price class (US/Europe edge locations only).
- Single instance everywhere (`desired_count = 1`, no Multi-AZ) — cheapest, zero
  redundancy; acceptable for a non-production environment.
- Odoo's Fargate task (`1024 CPU / 2048 MB`) and the two separate ALBs (one per
  stack) are the two line items NOT already minimal by construction — Odoo's size is
  hardcoded (not a tfvars knob) because Odoo is genuinely heavier than api/worker; the
  second ALB is deliberate isolation, not oversight, and the cheapest way to remove it
  (routing Odoo through the main ALB) is a real design change, not a flag flip.
- Rough floor estimate, 24/7, even at zero traffic: Aurora (~$44) + Odoo RDS (~$14) + 3
  Fargate tasks (~$72) + 2 ALBs (~$33) + Secrets Manager/CloudWatch/S3/SNS-SQS (~$5) ≈
  **~$165-170/month** (public AWS list pricing, not a quote — varies with traffic/storage).

## Resiliency
- SQS visibility-timeout retries + DLQ (`maxReceiveCount=5`); outbox relay at-least-once
  with consumer dedup (`processed_events`); reconcile sweeper as the fallback for missed/
  dropped inbound webhooks, on a per-connection advisory lock (safe with >1 worker
  replica).
- ECS service rollback on a failed deployment (AWS default); health checks on every ALB
  target group (api `/readyz`, Odoo `/web/login`) gate traffic shifting.

## Resolved decisions (were "open items" before Increment 7's code; now settled by what's actually built)
- **Aurora Serverless v2 — chosen and built** (`modules/database`). RDS plain was the
  alternative; not used.
- **ALB + Fargate — chosen and built** (`modules/compute`, `modules/odoo`). API Gateway
  was the alternative; not used.
- **One Cognito pool, not two** — the original design envisioned separate reseller/
  operator pools; the code that was actually built uses a single pool with
  `cognito:groups`/`custom:tenant_id` doing the split. Documented here so a future reader
  doesn't treat the single-pool reality as drift from an undocumented decision.
- **EventBridge Scheduler was planned, an in-process worker loop was built** —
  `ReconcileScheduler` (`src/worker/scheduler.py`) on a plain `time.sleep` loop,
  `RECONCILE_INTERVAL_SECONDS` (30s in staging). Simpler to deploy (no separate scheduled
  Lambda/rule), same effect at the current single-worker-replica scale.
- **Cognito on floci was "partial" — still true**, unchanged. Local dev uses the
  JWT/header stub; real Cognito is AWS-only.

## Open items (genuinely still open)
- Private networking (NAT or VPC endpoints) so `public_access=false` is a complete
  lock-down, not just a security-group change — see "Known gap" above.
- Consolidating Odoo behind the main ALB (cost lever, not done — see "Sizing decisions").
- Scoping the GitHub deploy role down from `AdministratorAccess` once real customer data
  is onboarded (see ADR-0020's "Revisit when").
- A real `terraform apply` against this plan and a live `deploy.yml` run have not been
  executed yet as of this revision — `plan` is verified clean; `apply` is the next human
  action (see "One-time account bootstrap").

## Revision history
- **2026-09-27 (Increment 3, Phase 3)**: original version — floci/AWS mapping, flat
  Terraform file layout (`messaging.tf`/`secrets.tf`/`data_aws.tf`), two-pool Cognito
  plan, EventBridge Scheduler plan.
- **2026-10-13/14 (Increment 7, continued, this revision)**: Terraform modules
  (`network`/`database`/`registry`/`identity`/`observability`/`iam`/`compute` split out
  of the old flat files, `odoo` and `ui` added new); one-time account bootstrap
  documented; full GitHub Actions `deploy.yml`/`terraform-plan.yml` CI/CD documented;
  Odoo's parallel stack and the UI's S3+CloudFront+CloudFront-as-reverse-proxy
  documented; `public_access` trade-off and its known gap documented; sizing/cost review
  added; resolved vs. still-open items split out; `terraform plan` verified clean (87
  resources) against the real `staging` backend.
