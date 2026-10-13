# ADR-0020: Terraform + AWS deployment and GitHub Actions CI/CD

| | |
|---|---|
| Status | Accepted |
| Affects | `infra/terraform/`, `.github/workflows/`, `Dockerfile.api`, `Dockerfile.worker`, `docker-compose.yml` |

## In one sentence

The already-designed target infrastructure is realized as Terraform (one AWS environment named `staging`, provisioned from GitHub Actions over OIDC), and the quality gates plus build/apply/migrate are automated as GitHub Actions.

## Why this needed a decision

The target architecture (`aidlc-docs/construction/target-arch/infrastructure-design/`) specified the resources and the floci↔AWS parity, but no Terraform, container images, or pipelines existed on disk. This ADR records the delivery choices.

## The decisions

| Topic | Decision | Why |
|---|---|---|
| Provisioner | Terraform, single config, `use_floci` toggle | Same config runs messaging/secrets locally on floci and the full stack on AWS; mirrors the app's `AWS_ENDPOINT_URL` approach |
| Environments | One AWS env, named `staging` | A single deploy target for now; `staging` is the honest label for a public, debug-friendly environment (not `prod`) |
| CI→AWS auth | GitHub OIDC → short-lived IAM role, `AdministratorAccess` | No long-lived AWS keys stored in GitHub. `AdministratorAccess` (not a hand-picked set of `*FullAccess` policies) because `terraform apply` from this role touches every module in the config — VPC, RDS, IAM, Cognito, Secrets Manager, SNS/SQS, S3/CloudFront, ECR, ECS — and a hand-picked list silently breaks on the next module added instead of failing loudly now |
| ECR repos vs. image push order | `deploy.yml` applies `-target=module.registry` before `docker push` | A from-scratch account has no ECR repos yet; pushing before they exist fails. This makes the Deploy workflow self-sufficient — no human needs to `terraform apply` from their laptop before CI can push images (only before CI can be trusted to run at all — see the OIDC bootstrap step in `docs/deploy-aws.md`) |
| UI hosting | S3 (private) + CloudFront with Origin Access Control (`modules/ui`) | `ui/vite.config.ts` already assumed this ("deploy straight to an S3 bucket ... or behind CloudFront"); nothing provisioned it. `deploy.yml` builds the UI after `apply` (baking in the real ALB/Cognito endpoints as Vite env vars) and syncs to S3 + invalidates CloudFront |
| UI → api routing | ALB added as a second CloudFront origin, `/graphql*` routed there | The ALB is plain HTTP, CloudFront is always HTTPS — a browser can't call it directly (mixed content). Routing through the same distribution also makes it same-origin, sidestepping CORS, instead of adding a cert to the ALB just for this |
| Odoo image rebuilds | Only on `Dockerfile.odoo`/`modules/odoo` changes, or an explicit `rebuild_odoo` manual-run input | Odoo's ECR tags are immutable and its attachments live on the task's ephemeral disk; rebuilding+redeploying it on every unrelated push would wipe attachments and pay a multi-minute reboot for no reason |
| State | S3 bucket + DynamoDB lock table (one-time `bootstrap/`) | Standard remote state with locking; bucket is private + versioned + encrypted |
| Images → ECS | CI builds `api`/`worker`, pushes to ECR tagged with the commit SHA; Terraform sets the task-def image; `apply` rolls the service | Immutable, traceable images; the running revision is always a known commit |
| Migrations | One-off ECS `run-task` (`alembic upgrade head`) after `apply`, before services settle | The migration runs in-VPC with DB access, reusing the api image |
| Cognito | A single user pool (role via `cognito:groups`) | The app reads one `COGNITO_USER_POOL_ID`; the design's two-pool split was never in code |
| Reconcile scheduler | In-process in the worker (`RECONCILE_INTERVAL_SECONDS`) | Matches the running code; EventBridge Scheduler deferred (would be a worker split, not needed yet) |
| CI ruff scope | ruff runs on changed Python files only (lint-imports + pytest repo-wide) | Mirrors the pre-commit hook; the repo carries pre-existing repo-wide ruff debt that would otherwise fail CI on untouched legacy files |

## Public access (deliberate, flagged)

`var.public_access` (set `true` in `envs/staging.tfvars`) makes Aurora internet-accessible and gives Fargate tasks public IPs with `0.0.0.0/0` ingress on the DB/app ports, for debugging convenience. This was an explicit, informed owner decision.

- It controls **network reachability only** — Cognito JWT auth, the DB password, and Secrets Manager are always on. "Public" never means "unauthenticated".
- A public multi-tenant Postgres is high-risk: it is one of the most-scanned surfaces on AWS and exposes every tenant's data behind only a password. This is acceptable for a staging/debug environment with non-real data; it must not front real customer data.
- `public_access = false` is **not yet** the single lever this ADR originally claimed. It only removes the `0.0.0.0/0` security-group rules — `modules/compute` and `modules/odoo` hardcode `assign_public_ip = true` regardless of the flag, and there are no private subnets or NAT/VPC endpoints for a task to use instead. Making it a real lever is tracked below under "Revisit when."

## Consequences

| | |
|---|---|
| ✅ | One `terraform apply` provisions the full stack; CI enforces the same gates as the local hook; deploys are commit-traceable |
| ✅ | No AWS keys in GitHub; state is locked and encrypted |
| ⚠️ | `public_access = true` exposes the database to the internet — safe only because this is staging with non-real data |
| ⚠️ | `public_access = false` only closes security-group holes, not public IPs — see "Public access" above. Not a real private-networking option today |
| ⚠️ | The deploy role has `AdministratorAccess` — correct for a staging account doing its own thing, wrong for a shared/production account |
| ⚠️ | Cert-less by default: the ALB serves plain HTTP on `:80` until `acm_certificate_arn` is set (then it redirects `:80`→`:443`) |
| ⚠️ | `terraform init`/`validate`/`plan` have been run against the real `staging` backend and are clean. A real `apply` and a live `deploy.yml` run have not — that's still the next step (see `docs/deploy-aws.md`, "First deploy") |

## Revisit when

Real customer data is onboarded:
- Make `public_access = false` actually private: add private subnets + NAT (or VPC
  endpoints for ECR/Secrets Manager/CloudWatch Logs) to `modules/network`, and wire
  `assign_public_ip` in `modules/compute`/`modules/odoo` to `var.public_access` instead of
  the current hardcoded `true`.
- Add an ACM cert and a domain for the ALB.
- Replace the deploy role's `AdministratorAccess` with scoped per-service policies.

Or a second environment is needed (add prefixing to the un-prefixed SNS/SQS/Cognito names so two environments can share an account).
