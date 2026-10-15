#!/bin/bash
# Install Sales, Inventory, and Invoicing once. Later starts only boot the server.
# Re-running -i on every container start reinstalls modules and can fail.
set -e
code=0
python3 - <<'PY' || code=$?
import os
import sys

import psycopg2

host = os.environ.get("HOST", "odoo-db")
user = os.environ.get("USER", "odoo")
password = os.environ.get("PASSWORD", "odoo")
try:
    conn = psycopg2.connect(host=host, user=user, password=password, dbname="odoo")
except Exception:
    sys.exit(10)
cur = conn.cursor()
cur.execute("SELECT to_regclass('public.ir_module_module')")
if cur.fetchone()[0] is None:
    sys.exit(10)
cur.execute("SELECT state FROM ir_module_module WHERE name = 'sale_management'")
row = cur.fetchone()
sys.exit(0 if row and row[0] == "installed" else 10)
PY
if [[ "$code" -eq 10 ]]; then
  /entrypoint.sh odoo -d odoo -i base,contacts,sale_management,stock,sale_stock --without-demo=all --stop-after-init
elif [[ "$code" -ne 0 ]]; then
  exit "$code"
fi

# A plain module install leaves internal users out of Sales and Invoicing, so
# sale.order reads fail. Grant those rights, and Inventory when it is installed.
/entrypoint.sh odoo shell -d odoo --no-http \
  --db_host="${HOST:-odoo-db}" \
  --db_user="${USER:-odoo}" \
  --db_password="${PASSWORD:-odoo}" <<'PY'
groups = [
    env.ref("sales_team.group_sale_manager"),
    env.ref("account.group_account_manager"),
]
if env["ir.module.module"].search([("name", "=", "stock"), ("state", "=", "installed")], limit=1):
    groups.append(env.ref("stock.group_stock_manager"))
internals = env["res.users"].search([("share", "=", False)])
missing_groups = [(user, group) for user in internals for group in groups if group not in user.groups_id]
for user, group in missing_groups:
    user.write({"groups_id": [(4, group.id)]})
if missing_groups:
    env.cr.commit()
PY

exec /entrypoint.sh odoo -d odoo --proxy-mode
