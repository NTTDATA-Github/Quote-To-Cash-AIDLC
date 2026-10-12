# Local setup

Get the platform running locally with no cloud account. Backing services run in Docker
(Postgres + the **floci** AWS emulator + Odoo); the `api` and `worker` processes run from
your venv (no `app`/`worker` docker-compose services yet — that's item F, still pending;
see `aidlc-docs/aidlc-state.md` for current status).

## 1. Prerequisites
- Python 3.11+
- Docker + Docker Compose

## 2. Install the package (editable, with dev tools)
```bash
python -m venv .venv
. .venv/Scripts/activate        # Windows;  source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
```

## 3. Start and stop
```bash
bash scripts/local.sh up
bash scripts/local.sh down
```
`up` starts Postgres, Floci, and Odoo, applies migrations, provisions queues, seeds the
demo tenant, and starts the api, worker, the reseller mock, AdminOps (if `ui/node_modules` exists), and the
coding agent (if `erp-agent-service/.env` exists).
`down` stops those processes and the containers. Volumes stay, so the next `up` keeps
the database and the Odoo install.

First Odoo boot installs modules and takes a few minutes. Every local URL, the demo
logins, and what the Odoo push-service banner means are in the README's "Run locally"
section. Floci's console needs the Docker socket mounted on the `floci` service, which
`docker-compose.yml` does.

The sections below are the same steps, run by hand.

## 4. Create the database schema
```bash
export DATABASE_URL=postgresql+psycopg2://portal:portal@localhost:5432/portal
alembic upgrade head
```
This creates the event store, outbox, projections, config/tenancy tables, the three
uniqueness constraints, and the row-level-security policies (see `docs/database-schema.md`).

## 5. Provision the messaging topology (on floci)
```bash
export AWS_ENDPOINT_URL=http://localhost:4566
export AWS_DEFAULT_REGION=us-east-1
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test
python -m scripts.messaging_bootstrap
python -m scripts.seed_demo    # connection, verified binding, subsidiary, quote qte_demo
```

## 6. Run the api + worker
```bash
export APP_PROFILE=postgres ERP_ADAPTER_MODE=stub   # stub: no live Odoo/HTTP needed
python -m src.worker.main &
uvicorn src.api.app:app --port 8000 &
```
`GET http://127.0.0.1:8000/livez` should return `{"status":"ok"}`. Without step 7, every
GraphQL request authenticates via the header stub (`x-tenant-id`/`x-roles`) — fine for
local dev, not real auth.

## 7. (Optional) Real Cognito auth instead of the header stub
floci emulates Cognito too. Provision a user pool + a demo user, then point the app at it:
```bash
python - <<'PY'
import boto3
c = boto3.client("cognito-idp", endpoint_url="http://localhost:4566", region_name="us-east-1")
pool = c.create_user_pool(PoolName="o2c-local",
    Schema=[{"Name": "tenant_id", "AttributeDataType": "String", "Mutable": True}])
pool_id = pool["UserPool"]["Id"]
client_id = c.create_user_pool_client(UserPoolId=pool_id, ClientName="local",
    ExplicitAuthFlows=["ALLOW_ADMIN_USER_PASSWORD_AUTH"])["UserPoolClient"]["ClientId"]
c.admin_create_user(UserPoolId=pool_id, Username="demo-operator",
    UserAttributes=[{"Name": "custom:tenant_id", "Value": "tnt_demo"}],
    MessageAction="SUPPRESS", TemporaryPassword="TempPass123!")
c.admin_set_user_password(UserPoolId=pool_id, Username="demo-operator", Password="DemoPass123!", Permanent=True)
c.create_group(GroupName="OPERATOR", UserPoolId=pool_id)
c.admin_add_user_to_group(UserPoolId=pool_id, Username="demo-operator", GroupName="OPERATOR")

# A reseller demo user too — no group needed: the reseller GraphQL schema has no role
# requirement (only the operator schema calls require_role), and the UI treats "no
# OPERATOR group" as reseller by default (App.tsx).
c.admin_create_user(UserPoolId=pool_id, Username="demo-reseller",
    UserAttributes=[{"Name": "custom:tenant_id", "Value": "tnt_demo"}],
    MessageAction="SUPPRESS", TemporaryPassword="TempPass123!")
c.admin_set_user_password(UserPoolId=pool_id, Username="demo-reseller", Password="DemoPass123!", Permanent=True)

print(f"COGNITO_USER_POOL_ID={pool_id}")
print(f"COGNITO_CLIENT_ID={client_id}")
PY
```
Both demo users land in the same tenant (`tnt_demo`) so they see the same seeded
connection/binding/items from step 5 — `demo-operator` for the admin screens,
Sign in to AdminOps as `demo-operator`. `demo-reseller` is a machine-role user, not a screen.
Export those two values, restart `api` (step 6), then get a real token and use it:
```bash
export COGNITO_USER_POOL_ID=...  COGNITO_CLIENT_ID=...
# (restart uvicorn so it picks up the new env)
TOKEN=$(python -c "
import boto3
c = boto3.client('cognito-idp', endpoint_url='http://localhost:4566', region_name='us-east-1')
auth = c.admin_initiate_auth(UserPoolId='$COGNITO_USER_POOL_ID', ClientId='$COGNITO_CLIENT_ID',
    AuthFlow='ADMIN_USER_PASSWORD_AUTH', AuthParameters={'USERNAME':'demo-operator','PASSWORD':'DemoPass123!'})
print(auth['AuthenticationResult']['IdToken'])
")
curl -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"query":"{ orders { orderId status } }"}' http://127.0.0.1:8000/graphql/reseller
```
A request with no/garbage token now gets a `401`, not a fallback tenant — see
`aidlc-docs/inception/application-design/target-architecture.md`'s implementation-status
note and §11 SEC-08.

## 7b. (Optional) Machine-to-machine auth (`client_credentials`) instead of user login
For a backend integrating with the GraphQL API directly — no human logging in. Same
`CognitoIdentityProvider`, same `COGNITO_USER_POOL_ID`/`COGNITO_CLIENT_ID` env vars from
step 7 — nothing about `api/app.py` or the container wiring changes for this; the
provider just recognizes the token shape (`token_use=access`) and reads tenant/roles from
OAuth **scopes** instead of user attributes (there's no user). Provision a resource
server + an M2M app client on the *same* pool from step 7:
```bash
python - <<'PY'
import boto3
c = boto3.client("cognito-idp", endpoint_url="http://localhost:4566", region_name="us-east-1")
pool_id = "..."  # from step 7
c.create_user_pool_domain(Domain="o2c-local", UserPoolId=pool_id)  # required for the OAuth token endpoint
c.create_resource_server(UserPoolId=pool_id, Identifier="o2c", Name="Order-to-Cash Connector API",
    Scopes=[{"ScopeName": "tenant.tnt_demo", "ScopeDescription": "act as tnt_demo"},
            {"ScopeName": "role.RESELLER", "ScopeDescription": "reseller-level access"}])
client = c.create_user_pool_client(UserPoolId=pool_id, ClientName="m2m-backend", GenerateSecret=True,
    AllowedOAuthFlows=["client_credentials"], AllowedOAuthFlowsUserPoolClient=True,
    AllowedOAuthScopes=["o2c/tenant.tnt_demo", "o2c/role.RESELLER"])
print("client_id:", client["UserPoolClient"]["ClientId"])
print("client_secret:", client["UserPoolClient"]["ClientSecret"])
PY
```
Then, against **real AWS** (not floci — see the gap below), get a token:
```bash
curl -u "$CLIENT_ID:$CLIENT_SECRET" \
  -d "grant_type=client_credentials&scope=o2c/tenant.tnt_demo%20o2c/role.RESELLER" \
  "https://o2c-local.auth.us-east-1.amazoncognito.com/oauth2/token"
# -> {"access_token": "...", "token_type": "Bearer", "expires_in": 3600}
```

> **floci gap, confirmed by testing, not assumed**: floci implements the `cognito-idp`
> service API (`create_user_pool_client`, `admin_initiate_auth`, etc.) but **not**
> Cognito's separate OAuth2 `/oauth2/token` HTTP endpoint — calling it locally routes to
> floci's S3 handler instead (visible in its own logs) and never reaches Cognito. So the
> `client_credentials` **token exchange** above can't be exercised against floci; only
> real AWS. What's still fully verified locally: the **token verification** logic
> (signature/issuer/scope-parsing) — `src/shared/identity/tests/test_cognito.py` covers
> it with fabricated tokens, and `tests/integration/test_cognito_identity.py` confirms
> the JWKS/signature machinery itself works against a real floci-issued access token
> (just not one with real `client_credentials` scopes, which floci can't produce).

## 8. Connect Odoo inbound webhooks (to collect status back)
Odoo Community has no native "webhook" action, so this uses a dedicated
shared-secret-in-path endpoint instead of the HMAC-signed one ERPNext gets — full setup
(secret provisioning, the Automation Rule's Python code, payload shape, verification) is
in **`docs/erps/odoo/webhook.md`**. The full quotation → delivery → invoice walk is
**`docs/erps/odoo/supply-chain-check.md`**. Until a connection's webhook is configured, the
reconciliation sweeper polls status as the fallback — every connection gets that either
way, the webhook only lowers latency.

## 9. Run the checks
```bash
pytest src tests    # unit + integration tests (co-located per module + tests/e2e);
                     # tests/integration/* self-skip with a clear reason if Postgres/floci aren't reachable
mypy src             # strict typing
ruff check src       # lint
lint-imports         # architecture boundaries (domain must not import infra/cloud SDKs)
```

## Where things live
See `aidlc-docs/construction/target-arch-project-structure.md` for the "where do I find X"
map (inbound webhooks, public GraphQL, the shared library, migrations, tests, etc.), or
`aidlc-docs/inception/application-design/target-architecture.md` for the architecture
itself and `docs/database-schema.md` for every table.
