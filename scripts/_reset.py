"""Temporary admin helper: fix the Odoo label in-place and kill zombie worker/NetSuite
service processes so a single clean set can be started. Writes a report to .local/reset.txt."""

from __future__ import annotations

import subprocess

from sqlalchemy import create_engine, text

URL = "postgresql+psycopg2://portal:portal@127.0.0.1:5432/portal"
OUT = ".local/reset.txt"


def _kill(pattern: str) -> str:
    ps = (
        "Get-CimInstance Win32_Process | "
        f"Where-Object {{ $_.CommandLine -match '{pattern}' }} | "
        "ForEach-Object { $_.ProcessId; Stop-Process -Id $_.ProcessId -Force }"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return (result.stdout or "").strip() or "(none)"


def main() -> None:
    lines: list[str] = []
    engine = create_engine(URL, future=True)
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE erp_connections SET instance_label = 'Odoo' "
                "WHERE connection_id = 'conn_odoo_local'"
            )
        )
    lines.append("odoo label updated -> 'Odoo'")
    lines.append("killed worker.main PIDs: " + _kill("src.worker.main"))
    lines.append("killed mock_netsuite PIDs: " + _kill("scripts.mock_netsuite"))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("done")


if __name__ == "__main__":
    main()
