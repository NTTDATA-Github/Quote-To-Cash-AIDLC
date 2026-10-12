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
| CI→AWS auth | GitHub OIDC → short-lived IAM role | No long-lived AWS keys stored in GitHub |
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
- Flipping `public_access = false` is the single lever to lock the environment down: Aurora + Fargate go private, the ALB stays the only public ingress, and the DB is reached via ECS Exec or an SSM tunnel instead (see `docs/deploy-aws.md`). The resource names and wiring do not change.

## Consequences

| | |
|---|---|
| ✅ | One `terraform apply` provisions the full stack; CI enforces the same gates as the local hook; deploys are commit-traceable |
| ✅ | No AWS keys in GitHub; state is locked and encrypted |
| ⚠️ | `public_access = true` exposes the database to the internet — safe only because this is staging with non-real data |
| ⚠️ | Cert-less by default: the ALB serves plain HTTP on `:80` until `acm_certificate_arn` is set (then it redirects `:80`→`:443`) |
| ⚠️ | A full AWS `apply` and a live pipeline run were not executed in the authoring sandbox (no `terraform` binary, no AWS, limited network) — Terraform is `fmt`/`validate`-structured and the workflows are authored; verification steps are in `docs/deploy-aws.md` |

## Revisit when

Real customer data is onboarded (flip `public_access` to false, add an ACM cert and a domain, split IAM deploy permissions off the managed `*FullAccess` policies), or a second environment is needed (add prefixing to the un-prefixed SNS/SQS/Cognito names so two environments can share an account).
