"""ERP field-mapping proposer.

Given sample export(s) from an ERP and a canonical field list the operator defines, an
LLM proposes how each ERP field maps onto the canonical fields — a draft a human reviews
before anyone writes an adapter. Operator-only (never a reseller surface): the proposer
reads ERP field names and sample values, which are ERP identity (FR-19).

Was a standalone service (erp-mapping-service + a Streamlit UI) before Increment; folded
into the portal so there is one authenticated surface and one Postgres store. Approving a
reviewed mapping is handed off over HTTP to `erp-agent-service`, which stays separate
because it shells out to `git`/`claude` on its host — see `infrastructure/agent_launcher.py`.
"""
