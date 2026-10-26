"""The ERP types an operator can connect without a developer, and the fields each one asks for.

The UI builds its add/edit form from this list, so adding an ERP here (plus its adapter in
`integration/erp/infrastructure/registry.py`) is the whole change — no screen to write.
An ERP missing from this list can still be onboarded through the "Other" path.
"""

from __future__ import annotations

from dataclasses import dataclass

# Where a field's value goes when the connection is saved.
#   LABEL      -> instance_label          BASE_URL   -> base_url
#   CREDENTIAL -> credentials[key]        SECRET     -> the stored secret (never returned)
TARGET_LABEL = "LABEL"
TARGET_BASE_URL = "BASE_URL"
TARGET_CREDENTIAL = "CREDENTIAL"
TARGET_SECRET = "SECRET"


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    hint: str
    target: str
    secret: bool = False


@dataclass(frozen=True)
class ErpSpec:
    code: str  # the stored erp_type, e.g. "ODOO"
    name: str  # what the operator sees
    auth_type: str  # AuthType name, e.g. "BASIC"
    fields: tuple[FieldSpec, ...]


ERP_CATALOG: tuple[ErpSpec, ...] = (
    ErpSpec(
        code="ODOO",
        name="Odoo",
        auth_type="BASIC",
        fields=(
            FieldSpec(
                key="instance_label",
                label="Name",
                hint="What your team calls this system",
                target=TARGET_LABEL,
            ),
            FieldSpec(
                key="base_url",
                label="Web address",
                hint="The address you open in your browser, e.g. http://odoo.example.com:8069",
                target=TARGET_BASE_URL,
            ),
            FieldSpec(
                key="database",
                label="Database",
                hint="The database name shown when you sign in",
                target=TARGET_CREDENTIAL,
            ),
            FieldSpec(
                key="username",
                label="Login",
                hint="The user name you sign in with",
                target=TARGET_CREDENTIAL,
            ),
            FieldSpec(
                key="password",
                label="Password",
                hint="Stored encrypted; leave blank when editing to keep the current one",
                target=TARGET_SECRET,
                secret=True,
            ),
        ),
    ),
)


def find_erp(code: str) -> ErpSpec | None:
    return next((spec for spec in ERP_CATALOG if spec.code == code), None)
