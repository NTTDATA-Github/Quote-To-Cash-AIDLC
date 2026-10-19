# Deploying to Azure

The portal runs on Azure (ADR-0023). Terraform for the Azure stack lives in `infra/azure/`.
Odoo runs on AWS (`infra/aws-odoo-poc/`), and Bedrock is an optional LLM provider for the
mapping proposer. No AWS service is otherwise used.

> **Always pass the real `TF_VAR_odoo_db_password` on every apply, never a placeholder.**
> `modules/keycloak` reads this variable to build its live `KC_DB_PASSWORD`. A placeholder
> silently breaks Keycloak's database connection, and Keycloak crash-loops with
> `password authentication failed`.

> **Same trap for `TF_VAR_db_password` (the portal DB).** `modules/database`'s
> `database_url` output embeds it directly into `DATABASE_URL` on api and worker. A wrong
> value doesn't fail at apply time; it shows up as `password authentication failed for
> user "portal"` in the worker logs.

> **A fresh portal Postgres server has no schema until Alembic runs against it.** Until a
> migration job exists, run it by hand once per fresh database:
> `az containerapp exec -g rg-o2c-staging -n o2c-staging-worker --revision <current>`,
> then inside the shell `python -m alembic upgrade head`. Check with `alembic current`
> against `alembic heads`.

## Prerequisites

- An Azure subscription and a resource group (`rg-o2c-staging` by default).
- Terraform 1.12.x and the Azure CLI, logged in with `az login`.
- An Entra External ID tenant. Terraform can't create it, so create it by hand in the Azure
  portal and note the tenant ID.
- Docker, for building the images.

## One-time bootstrap

1. **Remote state.**
   ```bash
   cd infra/azure/bootstrap
   terraform init
   terraform apply -var="state_storage_account=<globally-unique-name>"
   ```
   Copy the output into `infra/azure/envs/staging.backend.tfbackend`.
2. **GitHub OIDC (optional, for CI).** Create an App Registration with a federated
   credential for `repo:<owner>/<repo>:ref:refs/heads/main`, and grant it `Contributor` and
   `User Access Administrator` on the resource group. There is no deploy workflow in the
   repo yet, so this is only needed when one is added.

## Deploy

1. **Infrastructure.**
   ```bash
   cd infra/azure
   terraform init -backend-config=envs/staging.backend.tfbackend
   export TF_VAR_db_password='<strong password>'
   export TF_VAR_odoo_db_password='<different strong password>'
   terraform plan -var-file=envs/staging.tfvars   # review before applying
   terraform apply -var-file=envs/staging.tfvars
   ```
2. **Images and container apps.** Builds and pushes the api, worker and mock images to ACR,
   then updates the container apps to the new tag:
   ```bash
   bash scripts/deploy_azure.sh            # tags with a timestamp
   bash scripts/deploy_azure.sh <tag>      # or pass a tag
   ```
3. **Migrations.** Run `alembic upgrade head` as described in the warning above.
4. **Seed (staging only).** `scripts/seed_demo.py` recreates demo data. Staging has no real
   customer data.
5. **UI.** The UI is a static build served from the Azure storage account behind Front Door.
   Build it with the Azure endpoints (`VITE_GRAPHQL_URL`, `VITE_KEYCLOAK_ISSUER_URL`,
   `VITE_KEYCLOAK_CLIENT_ID`, from `terraform output` and `ui/.env.example`), then upload
   `ui/dist` to the UI storage container and purge the Front Door cache. This step isn't
   scripted yet.

## Self-check

```bash
cd infra/azure
terraform fmt -check -recursive
terraform init -backend=false
terraform validate
```

`plan` and `apply` touch real, billable resources once a subscription is wired up. Run them
only after reviewing the plan.

## Resource mapping

| Module | Purpose |
|---|---|
| `registry` | Container Registry |
| `observability` | Log Analytics workspace |
| `identity` | Entra app registration and app role |
| `messaging` | Service Bus namespace, topic and subscriptions |
| `database` | Postgres Flexible Server (portal DB) |
| `iam` | User-assigned managed identities and role assignments |
| `secrets` | Key Vault |
| `compute` | Container Apps environment and api/worker container apps |
| `ui` | Storage static website and Front Door |
| `keycloak` | Keycloak container app |
| `foundry` | Foundry model deployment |
| `agent` | Coding agent container app (optional) |
| `mocks` | NetSuite and reseller mock container apps |
| `odoo` | Odoo container app and its Postgres server. Pending removal, see the open item below. |
| `bootstrap` | Storage account and container for remote state |

## Open item: the `odoo` module

Odoo runs on AWS, so the `odoo` module should not be deployed to Azure. The Postgres server
inside that module also hosts Keycloak's database (`modules/keycloak` reads
`module.odoo.db_server_id`). Removing the module as it stands would destroy Keycloak's
database. Split the database into its own module before removing the Odoo container app.
