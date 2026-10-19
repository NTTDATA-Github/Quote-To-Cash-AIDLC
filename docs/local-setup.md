# Local setup

`bash scripts/local.sh up` starts the whole demo on your machine: Odoo and Keycloak in
Docker, the api and the seed on the host, and the reseller and NetSuite mocks, AdminOps, and
the coding agent. It needs no cloud account. The README has the URLs and the sign-in details.

## Prerequisites

- Docker Desktop, running
- Python 3.11 and Node 20
- Git Bash on Windows (the script runs under bash)

## Steps

```bash
python -m venv .venv
. .venv/Scripts/activate          # source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
cd ui && npm install && cd ..
bash scripts/local.sh up
```

Sign in to AdminOps at http://127.0.0.1:5173 as `operator1` / `operator1`.

Stop with `bash scripts/local.sh down`. Docker volumes are kept.

## What runs where

| Piece | Where | Notes |
|---|---|---|
| api | host, `APP_PROFILE=memory` | State is in memory and reseeded on each `up`. |
| Odoo + its Postgres | Docker (`odoo`, `odoo-db`) | Admin `admin` / `admin`. First boot is slow. |
| Keycloak | Docker (`keycloak`) | Realm `o2c` is imported from `keycloak-realm-export.json`. |
| seed | host, `scripts/seed_demo.py` | Creates Odoo data, then connections, bindings and routes through the operator GraphQL API. Registers the reseller webhook. |
| reseller mock | host | Signing secret comes from `.local/reseller-secret`. |
| NetSuite mock | host | SuiteTalk REST on port 8075. |
| AdminOps | host, Vite dev server | Keycloak issuer and client come from `scripts/local.sh`. |

## Notes

- The memory profile runs the order pipeline synchronously in process. The worker, the
  outbox relay and Service Bus are not used locally.
- Mapping proposals use a deterministic stub locally, so no LLM or Bedrock call is made.
- The Postgres service in `docker-compose.yml` is for `tests/integration/` only.

## Troubleshooting

- **Keycloak does not come up.** Check `docker compose logs keycloak`. The realm import runs
  on first boot.
- **Sign-in fails with "Account is not fully set up".** The demo user needs first and last
  name in the realm export. See `Dockerfile.keycloak`.
- **Seed fails on Odoo.** Odoo is still installing modules. Wait for
  http://localhost:8069/web/login, then run `bash scripts/local.sh up` again. Set
  `ODOO_PARTNER_ID` to skip the Odoo step when Odoo isn't running. Don't run the seed
  against an api that is already seeded, because the in-memory state would get duplicates.
- **Stale data after a code change.** Restart with `bash scripts/local.sh up`, which restarts
  the api and reseeds it.
