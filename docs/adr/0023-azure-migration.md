# ADR-0023: Migrate infrastructure from AWS to Azure

| | |
|---|---|
| Status | Proposed |
| Affects | `infra/azure/` (new), `infra/terraform/` (kept until cutover), `.github/workflows/`, `src/shared/{secrets,messaging,identity,llm}/` |

## In one sentence

Every AWS service in [ADR-0020](0020-terraform-aws-deploy-and-cicd.md)'s stack is replaced by its closest-fit Azure service, behind the same module boundaries and the same application-layer ports, with both stacks running in parallel until traffic cuts over.

## Why this needed a decision

The business decided to move all cloud infrastructure off AWS onto Azure. The app is a
modular monolith with cloud concerns kept behind ports (`SecretStore`,
`EventPublisher`/`MessageConsumer`, `IdentityProvider`, the LLM client) and their AWS
adapters isolated in `src/shared/{secrets,messaging,identity,llm}/aws.py` / `bedrock.py`
(ADR-0001's framework-free core). That boundary is what makes this a swap of adapters +
infrastructure rather than a rewrite — this ADR records which Azure service replaces which
AWS one, and what doesn't map 1:1.

## The decisions

| Topic | AWS (today) | Azure (target) | Why |
|---|---|---|---|
| Compute | ECS Fargate + ALB | **Azure Container Apps** | Serverless containers with built-in ingress/TLS for 3 stateless services; no cluster to run, no ALB/ACM equivalent needed |
| App database | Aurora Serverless v2 (Postgres 16) | **Postgres Flexible Server**, Burstable + storage autoscale | No serverless-v2-exact equivalent; Burstable+autoscale is the closest "pay for what you use" |
| Odoo database | RDS Postgres 15 | **Postgres Flexible Server** (2nd instance) | `require_secure_transport = OFF` replaces `rds.force_ssl=0` |
| Pub/sub | SNS FIFO topic → 5 SQS FIFO queues + DLQs | **Service Bus Standard**: 1 topic → 5 subscriptions, sessions on | Subscriptions ARE the queues; dead-lettering is built into every subscription — no separate DLQ resource. SQL filter rules replace SNS filter policies |
| Secrets | Secrets Manager | **Azure Key Vault** | Closest managed-secret store; name charset (`[0-9a-zA-Z-]`, no `/`) forces a `secret_ref` naming change |
| Container registry | ECR | **Azure Container Registry** | Direct equivalent |
| Operator identity | Cognito user pool + app client | **Microsoft Entra External ID** app registration + app role | Closest hosted-identity service with app roles and OAuth code flow for a SPA. Tenant creation is a manual portal step — same category as today's human-run GitHub OIDC bootstrap |
| Logs | CloudWatch Logs | **Log Analytics workspace** | Container Apps' built-in sink |
| Static UI + API routing | S3 + CloudFront (`/graphql*` same-origin route) | **Storage static website + Azure Front Door Standard** | Front Door's path-based routes reproduce CloudFront's `ordered_cache_behavior` same-origin trick |
| One-off migration task | `aws ecs run-task` with a command override | **Container Apps Job** (manual trigger) | Closest "run this container once" primitive |
| CI→cloud auth | GitHub OIDC → IAM role | GitHub OIDC → **Entra federated credential** on an App Registration | No stored keys, same pattern as today; needs `Contributor` + `User Access Administrator` since Terraform also creates role assignments |
| Terraform state | S3 + DynamoDB lock table | **Storage Account + container**, `azurerm` backend | Blob lease handles locking; no separate lock table resource |
| LLM (field-mapping proposer) | Bedrock Converse via `boto3` | **Direct Anthropic API** (new adapter, `urllib` — no new dependency) | Azure has no first-party Claude hosting; the new adapter calls the Messages API directly with stdlib `urllib`, same as `bedrock.py`'s existing bearer-token path, so the `llm_proposer.py` port doesn't change and nothing new is added to `pyproject.toml` |
| Local dev (`use_floci`) | floci emulates SNS/SQS/Secrets/Cognito | **Not carried over** | azurerm talks to ARM, which nothing emulates locally, and there's no Key Vault/Entra emulator either; local dev keeps its current path |

## Consequences

| | |
|---|---|
| ✅ | Same module boundaries as `infra/terraform/` (`network`/`database`/`messaging`/`secrets`/`registry`/`identity`/`observability`/`iam`/`compute`/`ui`/`odoo`) — easy to diff the two stacks during the parallel-run phase |
| ✅ | Container Apps removes a whole category of AWS resources (ALB, listeners, target groups, ACM) with no replacement needed |
| ✅ | Service Bus's built-in dead-lettering removes 5 explicit DLQ resources + their queue policies |
| ⚠️ | Service Bus's `requires_session` (FIFO) and duplicate-detection are fixed at creation — get them right on the first `apply`, there's no toggling later without recreating the entity |
| ⚠️ | The azurerm provider (confirmed empirically, v4.81.0) cannot reliably manage a `azurerm_servicebus_subscription_rule` literally named `"$Default"` — both create and update silently delete the rule without recreating it ("Provider produced inconsistent result after apply"). Worked around by naming the managed rule `"event-type-filter"` instead and leaving the subscription's auto-created `$Default` alone (it ends up deleted as a side effect of the bug, which happens to be the desired end state, but isn't something to rely on) |
| ⚠️ | Key Vault's secret-name charset forces a `secret_ref` format change the app must read consistently on both the old and new secret store adapter |
| ⚠️ | Entra External ID's custom `tenant_id` claim and user-flow/branding config have no Terraform resource today — tracked as a manual/portal step, not automated |
| ⚠️ | Cognito passwords can't be exported — every operator account is recreated, not migrated |
| ⚠️ | The field-mapping proposer now calls an external API (Anthropic) directly over the network instead of riding inside the AWS SDK's existing auth — needs its own API key (Key Vault), no new package dependency |

## Revisit when

- Entra External ID (or whatever the custom-attribute/user-flow story becomes) gets a
  supported Terraform resource — re-evaluate the `identity` module's manual steps then.
- A first-party Claude-on-Azure offering ships — re-evaluate the LLM adapter.
- `infra/terraform/` is torn down after cutover — delete it and this ADR's "both stacks"
  caveat becomes moot.
