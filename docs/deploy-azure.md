# Migrating to Azure (Terraform + GitHub Actions)

This is the runbook for [ADR-0023](adr/0023-azure-migration.md): moving the `staging`
environment off AWS onto Azure. The Azure stack lives in `infra/azure/`, parallel to
`infra/terraform/` — both exist until cutover (Phase 8 below), so don't delete the AWS
config yet.

> **Always pass the real `TF_VAR_odoo_db_password` on every apply, never a placeholder.**
> It looks safe to pass a dummy value — `modules/odoo`'s Postgres server has
> `ignore_changes = [administrator_password]`, so the server itself never re-applies it —
> but `modules/keycloak` also reads this same variable to build its live
> `KC_DB_PASSWORD`, which is NOT covered by any `ignore_changes`. A placeholder here
> silently breaks Keycloak's DB connection (confirmed the hard way: a password reset that
> didn't fully propagate took Keycloak from `Succeeded` to crash-looping with
> `password authentication failed for user "odoo"`). Keep the real value somewhere
> durable, not just in a session scratchpad.

> **Same trap applies to `TF_VAR_db_password` (the portal DB), one level removed.**
> `modules/database`'s Postgres server also ignores `administrator_password` after
> creation, but `modules/database`'s own `database_url` output embeds `var.db_password`
> directly, and that output flows straight into `DATABASE_URL` on api/worker. Passing a
> placeholder here doesn't error at apply time — it just bakes a wrong password into every
> container until someone notices `FATAL: password authentication failed for user
> "portal"` in the worker logs. A real value is hardcoded in `infra/azure/terraform.tfvars`
> (gitignored) specifically so this can't drift silently again.

> **A fresh portal Postgres server has no schema until Alembic is run against it —
> nothing provisions this automatically yet.** `alembic`/`migrations/` are already in the
> api/worker image (Phase 4's plan always intended a Container Apps Job to run `alembic
> upgrade head` as part of CD), but that job was never built, so the step was just
> skipped. Symptom: worker logs show `psycopg2.errors.UndefinedTable: relation "outbox"
> does not exist` even though the DB connection itself is fine. Until the Container Apps
> Job exists, run it by hand once per fresh database:
> `az containerapp exec -g rg-o2c-staging -n o2c-staging-worker --revision <current> `
> then, inside the shell, `python -m alembic upgrade head` (verify with `alembic current`
> vs `alembic heads` — `--command` one-liners with shell redirection are unreliable here
> because `az containerapp exec` doesn't shell-quote consistently across `cmd.exe`).

## Decisions taken so far (defaults, not blockers)

Picked so the migration isn't stalled on open questions; change any of these in
`infra/azure/envs/staging.tfvars` or by asking before Phase 2:

| Decision | Default | Change it by |
|---|---|---|
| Region | `eastus` (parallel to `us-east-1`) | `var.location` |
| Resource group | `rg-o2c-staging` | `var.resource_group_name` |
| Compute | Azure Container Apps (not AKS) | — would need a new `compute` module |
| Data | **Reseed, don't migrate** — staging has no real customer data (ADR-0020), `scripts/seed_demo.py` recreates it | Run a `pg_dump`/`pg_restore` manually if that changes |
| Operator users | Recreated by hand (Cognito passwords don't export) | — |
| Entra tenant | Not yet created — **manual step, Phase 1** | — |
| LLM provider | Direct Anthropic API, replacing Bedrock | `MAPPING_BEDROCK_MODEL_ID` → a new `MAPPING_ANTHROPIC_MODEL` setting |
| `public_access` | Same lever as AWS: `true` by default (debug-friendly staging, not real data) | `var.public_access` |

## Estimated monthly cost

Pulled from Azure's Retail Prices API (eastus) against the actual SKUs this config uses,
assuming a near-idle staging workload (low traffic, containers mostly waiting rather than
under load — Container Apps bills active vCPU at ~8x the idle rate, so real usage would
push this up).

| Resource | SKU / config | Monthly estimate | Basis |
|---|---|---|---|
| Postgres Flexible Server (portal) | Burstable B1ms, 32GB | ~$16.10 | $0.017/hr compute (×730h) + $0.115/GB storage |
| Postgres Flexible Server (odoo) | Burstable B1ms, 32GB | ~$16.10 | same, second instance |
| Container App — api | 0.5 vCPU / 1Gi, mostly idle | ~$11.70 | idle vCPU + memory at $0.000003/unit-sec, 730h |
| Container App — worker | 0.5 vCPU / 1Gi, mostly idle | ~$11.70 | same (long-polling Service Bus counts as idle CPU) |
| Container App — odoo | 1 vCPU / 2Gi, mostly idle | ~$23.30 | same rate, double the allocation |
| Azure Front Door Standard | 1 profile, 2 routes | ~$35–38 | **$35/month flat base fee** + minimal data transfer |
| Service Bus namespace | Standard, 1 topic + 5 subscriptions | ~$10 | flat $10/month base unit |
| Container Registry | Basic | ~$5.30 | $0.1666/day base + ~$0.10/GB stored images |
| Log Analytics workspace | PerGB2018 | ~$0–7 | $2.30/GB beyond the free monthly allowance |
| Key Vault | Standard, 3 secrets | <$1 | $0.03 per 10,000 operations |
| Storage account (UI) | Standard LRS, static website | <$1 | a few MB of built UI assets |
| Everything else (RG, managed identities, role assignments, azuread app/SP/federated credential, Service Bus subscriptions/rules, firewall rules) | — | $0 | billed only through the resources above |

**Total: roughly $130–150/month** while idle. Two of these are a fixed floor regardless of
traffic: Front Door's $35/month base fee and the two Postgres servers (~$32/month
combined). Skipping `module.odoo` on an early apply drops ~$39/month and 9 resources with
no effect on the rest of the stack, if Odoo isn't needed immediately.

## What's actually been done

**Nothing has been applied — nothing here costs money yet.**
- `infra/azure/` — Terraform for every module. `terraform fmt -check` passes.
  `init`/`validate` have **not** been run (no registry access in the environment that
  wrote this) — run them yourself before trusting the HCL compiles. `plan`/`apply` need a
  real subscription and haven't been attempted.
- Phase 3's four adapters (`secrets/azure.py`, `messaging/azure.py`, `identity/entra.py`,
  `llm/anthropic.py`) are written, wired into `composition.py`/`worker/main.py` behind
  `CLOUD_PROVIDER=azure`, and each has a passing unit test (fakes/mocks — no network, no
  live Azure resource). `lint-imports` (all 4 contracts kept) and the full `pytest` suite
  (`APP_PROFILE=memory`) pass. `mypy` has **not** been run (not installed in that
  environment either).
- Everything else (Phases 1, 2, 4-8) is still just the plan below.

## Phased plan

### Phase 1 — Bootstrap (one-time, manual)
1. Create the Azure subscription/resource group if it doesn't exist.
2. **Create the Entra External ID tenant** (Azure portal → "Microsoft Entra External ID" →
   create tenant). This is the one step a human must do by hand, same reason the AWS GitHub
   OIDC role was human-run: Terraform can't create the identity it would authenticate
   against. Note the tenant ID.
3. Remote state:
   ```bash
   cd infra/azure/bootstrap
   terraform init
   terraform apply -var="state_storage_account=<globally-unique-name>"
   ```
   Put the output into `infra/azure/envs/staging.backend.tfbackend`.
4. GitHub OIDC: create an App Registration with a federated credential trusting this repo
   (`repo:<owner>/<repo>:ref:refs/heads/main`), grant it `Contributor` + `User Access
   Administrator` on the resource group. This is the Azure equivalent of today's
   `github_deploy_role_arn` bootstrap — also human-run, for the same reason.

### Phase 2 — Apply Azure infra, in parallel with AWS
```bash
cd infra/azure
terraform init -backend-config=envs/staging.backend.tfbackend
export TF_VAR_db_password='<strong password>'
export TF_VAR_odoo_db_password='<different strong password>'
terraform apply -var-file=envs/staging.tfvars
```
Both `infra/terraform` and `infra/azure` can be applied and left running at the same time —
they don't share any resources. AWS keeps serving real traffic through this phase.

### Phase 3 — Adapters behind the existing ports
Added, alongside the AWS adapters (neither replaces the other):
- `src/shared/secrets/azure.py` — `SecretStore` backed by Key Vault (`azure-keyvault-secrets`).
- `src/shared/messaging/azure.py` — `EventPublisher`/consumer backed by Service Bus
  (`azure-servicebus`); `MessageGroupId` → session id, consumer becomes a session receiver.
- `src/shared/identity/entra.py` — `IdentityProvider` verifying Entra-issued JWTs.
- `src/shared/llm/anthropic.py` — direct Anthropic API client implementing the same `ask()`
  shape as `bedrock.py`, over stdlib `urllib` — no new dependency.
- `Settings.cloud_provider` (`CLOUD_PROVIDER=aws|azure`) — `composition.py` and
  `src/worker/main.py` branch on it, same shape as the existing `profile` switch
  (`memory`/`postgres`).

**Done.** All four adapters exist, each with a unit test (fake client/credential
injection, no network — same pattern as `test_bedrock.py`/`test_cognito.py`). **Not done:**
running any of them against a real Azure resource — `tests/integration/` only exercises
the AWS path today. That's still ahead of actually pointing staging at Azure.

### Phase 4 — CI/CD rewrite
New workflow (`deploy-azure.yml`), parallel to `deploy.yml`:
`azure/login@v2` (OIDC) → ACR login/push → `terraform apply` → Container Apps Job for the
Alembic migration → wait for revision healthy → build UI with Azure endpoints baked in →
`az storage blob sync` + Front Door cache purge. Don't touch `deploy.yml` until cutover.

### Phase 5 — Data
Staging has no real customer data (see "Decisions" above), so the default is: apply Azure,
run `scripts/seed_demo.py` against it, done. If that assumption changes before cutover,
`pg_dump` the AWS Aurora cluster and `pg_restore` into the Azure Flexible Server instead.

### Phase 6 — Recreate operator users
Cognito user records (and passwords) don't export. Recreate each operator account in the
Entra External ID tenant and re-assign the `OPERATOR` app role by hand, or script it against
the Microsoft Graph API if the list is long.

### Phase 7 — Cut over
Point DNS / share the Front Door URL instead of the CloudFront one, confirm the Azure path
end-to-end (login, place an order, ERP delivery, UI), then stop sending traffic to the AWS
ALB/CloudFront.

### Phase 8 — Decommission AWS
Once Azure has run clean for a confidence period: `terraform destroy` in `infra/terraform/`,
remove `deploy.yml` and the AWS adapters (`src/shared/*/aws.py`, `bedrock.py`), drop `boto3`
from dependencies, delete ADR-0020's "both stacks" caveat from ADR-0023.

## Resource mapping

See [ADR-0023](adr/0023-azure-migration.md)'s decision table for the full AWS→Azure service
list and the reasoning behind each pick. Terraform-module-level mapping:

| `infra/terraform/modules/...` | `infra/azure/modules/...` |
|---|---|
| `network` | `network` — VNet + subnets + NSGs (no IGW equivalent needed; Container Apps/Front Door handle public ingress) |
| `database` | `database` — Postgres Flexible Server (portal DB) |
| `messaging` | `messaging` — Service Bus namespace + topic + subscriptions |
| `secrets` | `secrets` — Key Vault |
| `registry` | `registry` — Container Registry |
| `identity` | `identity` — Entra app registration + app role (tenant itself is manual, see Phase 1) |
| `observability` | `observability` — Log Analytics workspace |
| `iam` | `iam` — user-assigned managed identities + role assignments |
| `compute` | `compute` — Container Apps environment + api/worker container apps |
| `ui` | `ui` — Storage static website + Front Door |
| `odoo` | `odoo` — Container App + its own Postgres Flexible Server |
| `bootstrap` | `bootstrap` — Storage Account + container for remote state |

## Self-check

```bash
cd infra/azure
terraform fmt -check -recursive
terraform init -backend=false
terraform validate
```
Don't run `plan`/`apply` against a real subscription without confirming first — unlike
`fmt`/`validate`, those touch real (billable) Azure resources once a subscription is wired
up.
