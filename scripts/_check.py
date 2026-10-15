"""Temporary verification helper — writes current NetSuite-related DB state to a file."""

from __future__ import annotations

from sqlalchemy import create_engine, text

OUT = ".local/verify.txt"
URL = "postgresql+psycopg2://portal:portal@127.0.0.1:5432/portal"


def main() -> None:
    engine = create_engine(URL, future=True)
    lines: list[str] = []
    with engine.connect() as c:
        lines.append("=== erp_connections ===")
        for r in c.execute(
            text(
                "select connection_id, erp_type, instance_label, base_url "
                "from erp_connections order by connection_id"
            )
        ):
            lines.append(f"{r[0]} | {r[1]} | {r[2]} | {r[3]}")
        lines.append("=== netsuite bindings ===")
        for r in c.execute(
            text(
                "select binding_id, tenant_id, connection_id, erp_customer_id, status "
                "from tenant_connection_bindings where connection_id like 'conn_netsuite%'"
            )
        ):
            lines.append(f"{r[0]} | {r[1]} | {r[2]} | cust={r[3]} | {r[4]}")
        lines.append("=== netsuite routes/subsidiary ===")
        for r in c.execute(
            text(
                "select sr.subsidiary_id, s.name, sr.connection_id, sr.erp_company_id "
                "from subsidiary_routes sr join subsidiaries s "
                "on s.subsidiary_id=sr.subsidiary_id "
                "where sr.connection_id like 'conn_netsuite%'"
            )
        ):
            lines.append(f"{r[0]} | {r[1]} | {r[2]} | company={r[3]}")
        lines.append("=== orders on netsuite (any naming) ===")
        for r in c.execute(
            text(
                "select order_id, owning_connection_id, erp_order_id, client_reference, state "
                "from orders where owning_connection_id like 'conn_netsuite%' "
                "or order_id like 'ord_conn_netsuite%' order by order_id"
            )
        ):
            lines.append(f"{r[0]} | {r[1]} | erp={r[2]} | ref={r[3]} | {r[4]}")
        lines.append("=== leftover 'local' naming check ===")
        n = c.execute(
            text("select count(*) from erp_connections where connection_id='conn_netsuite_local'")
        ).scalar()
        lines.append(f"conn_netsuite_local rows: {n}")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
