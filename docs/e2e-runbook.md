# Local end-to-end runbook (floci + Terraform)

Brings up the full async system on a laptop: Postgres + floci (SNS/SQS/Secrets) + Odoo,
the api and worker processes, Terraform-provisioned messaging, and a real order flowing
through to an ERP. Everything here is local — no AWS account needed.

The fastest path is `scripts/local.sh up`, which already does migrate → messaging
bootstrap → seed → start api/worker. This runbook is the explicit, step-by-step version,
including the Terraform step.

## Prerequisites
- Docker + Docker Compose
- Python 3.11 and a virtualenv: `python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"`
  (POSIX: `.venv/bin/python`)
- Terraform >= 1.6 (only for the Terraform step)
- Node 20 + `npm --prefix ui install` (only if you want the UI)

## 1. Backing services
```bash
docker compose up -d            # postgres, floci, odoo, adminer
```

## 2. Provision local messaging (Terraform against floci)
This provisions only what floci emulates (SNS FIFO topic + SQS FIFO queues + DLQs +
Secrets Manager). All AWS-only resources are toggled off by `use_floci=true`.
```bash
terraform -chdir=infra/terraform init -backend=false
terraform -chdir=infra/terraform apply -var-file=envs/local.tfvars
```
This is equivalent to `python -m scripts.messaging_bootstrap`; use whichever you prefer.
The queue/topic names are identical either way.

## 3. Migrate + seed
```bash
export DATABASE_URL="postgresql+psycopg2://portal:portal@127.0.0.1:5432/portal"
export AWS_ENDPOINT_URL="http://127.0.0.1:4566"
export AWS_REGION=us-east-1 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test
export APP_PROFILE=postgres

.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m scripts.seed_demo
.venv/Scripts/python -m scripts.seed_cognito     # optional; writes .local/cognito.env
```

## 4. Start api + worker
```bash
.venv/Scripts/python -m uvicorn src.api.app:app --host 127.0.0.1 --port 8000
# in another shell:
.venv/Scripts/python -m src.worker.main
```
Or run everything the easy way: `bash scripts/local.sh up`.

## 5. Configure the Odoo inbound webhook (optional)
See `docs/odoo-webhook-setup.md` for the Odoo Automation Rule and the shared-secret URL.

## 6. Drive it
- Reseller GraphQL: http://127.0.0.1:8000/graphql/reseller
- Operator GraphQL: http://127.0.0.1:8000/graphql/operator
- Place an order (reseller `placeOrder`), then watch it move Submitted → Validated → Sent
  to ERP as the worker carries it through the outbox → SNS FIFO → SQS FIFO chain.
- App DB browser (Adminer): http://localhost:8088 · Floci console: http://localhost:4566/_floci/ui

## 7. Full stack in containers (optional)
Instead of host processes, run the same images CI builds:
```bash
docker compose --profile app up --build     # adds the `app` and `worker` containers
```

## Tear down
```bash
docker compose down          # keeps volumes; add -v to wipe data
```

## Deploying to AWS
See `docs/deploy-aws.md`.
