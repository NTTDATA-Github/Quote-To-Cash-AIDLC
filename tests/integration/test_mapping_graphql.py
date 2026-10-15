"""Operator GraphQL wiring for the ERP field-mapping proposer (memory profile).

Exercises the resolver layer end to end against the in-memory container: register a
canonical schema, submit a mapping (processed inline by the stub proposer in the memory
profile), poll it to DONE, approve it, and read the adapter run. Also checks the OPERATOR
role gate. Lives under tests/ (not under src/) because it imports the api host layer,
which the import-linter layered contract forbids module code from doing.
"""

from __future__ import annotations

from src.api.graphql.context import GraphQLContext
from src.api.graphql.operator.schema import build_operator_schema
from src.composition import build_container
from src.shared.config import Settings

_SCHEMA = build_operator_schema()

_CSV = "field,description\norder_id,The id\ncustomer,End customer\n"


def _settings() -> Settings:
    return Settings(
        profile="memory",
        database_url="",
        aws_endpoint_url=None,
        aws_region="us-east-1",
        domain_topic_arn="arn:aws:sns:us-east-1:000000000000:t.fifo",
        erp_adapter_mode="stub",
        erp_odoo_timeout_seconds=5.0,
        erp_netsuite_timeout_seconds=5.0,
        log_level="INFO",
        reconcile_interval_seconds=900,
        worker_roles=frozenset(),
        cognito_user_pool_id=None,
        cognito_client_id=None,
        cognito_resource_server_id="o2c",
        cors_allowed_origins=[],
        mapping_bedrock_model_id="stub-model",
        agent_service_url="http://localhost:8002",
        erp_probe_allow_private_addresses=False,
    )


def _context(roles: tuple[str, ...] = ("OPERATOR",)) -> GraphQLContext:
    container = build_container(_settings())
    return GraphQLContext(container=container, tenant_id="tnt_demo", roles=roles)


def test_operator_role_is_required() -> None:
    result = _SCHEMA.execute_sync("{ canonicalSchemas { name } }", context_value=_context(roles=()))
    assert result.errors
    assert "OPERATOR" in result.errors[0].message


def _register_connection(ctx: GraphQLContext, *, erp_type: str, label: str) -> str:
    result = _SCHEMA.execute_sync(
        """
        mutation($t:String!,$l:String!,$b:String!,$c:JSON!,$a:AuthConfigInput!){
          registerConnection(erpType:$t, instanceLabel:$l, baseUrl:$b, credentials:$c, auth:$a){
            connectionId
          }
        }
        """,
        variable_values={
            "t": erp_type,
            "l": label,
            "b": "https://erp.example.invalid",
            "c": {},
            "a": {"authType": "NONE", "params": {}, "secret": None},
        },
        context_value=ctx,
    )
    assert result.errors is None, result.errors
    return result.data["registerConnection"]["connectionId"]


def test_register_submit_poll_approve_flow() -> None:
    ctx = _context()

    reg = _SCHEMA.execute_sync(
        "mutation($n:String!,$c:String!){"
        " registerCanonicalSchema(name:$n,csvText:$c){ name fieldCount } }",
        variable_values={"n": "orders", "c": _CSV},
        context_value=ctx,
    )
    assert reg.errors is None, reg.errors
    assert reg.data == {"registerCanonicalSchema": {"name": "orders", "fieldCount": 2}}

    listed = _SCHEMA.execute_sync("{ canonicalSchemas { name fieldCount } }", context_value=ctx)
    assert listed.data == {"canonicalSchemas": [{"name": "orders", "fieldCount": 2}]}

    connection_id = _register_connection(ctx, erp_type="NETSUITE", label="NetSuite")

    submit = _SCHEMA.execute_sync(
        """
        mutation($conn:String!,$files:[SampleFileInput!]!,$schema:String){
          submitMapping(connectionId:$conn, sampleFiles:$files, schemaName:$schema){ jobId status }
        }
        """,
        variable_values={
            "conn": connection_id,
            "files": [{"filename": "orders.csv", "content": "ORDER_ID,CUSTOMER\n1,Acme\n"}],
            "schema": "orders",
        },
        context_value=ctx,
    )
    assert submit.errors is None, submit.errors
    job_id = submit.data["submitMapping"]["jobId"]

    # memory profile processes inline on submit, so the job is already DONE on first poll
    poll = _SCHEMA.execute_sync(
        "query($id:String!){"
        " mappingJob(jobId:$id){ status mapping{ erpField canonicalField } error } }",
        variable_values={"id": job_id},
        context_value=ctx,
    )
    assert poll.errors is None, poll.errors
    assert poll.data["mappingJob"]["status"] == "DONE"
    canon = {m["canonicalField"] for m in poll.data["mappingJob"]["mapping"]}
    assert canon == {"order_id", "customer"}

    approve = _SCHEMA.execute_sync(
        "mutation($id:String!){ approveMapping(jobId:$id){ adapterRunId } }",
        variable_values={"id": job_id},
        context_value=ctx,
    )
    assert approve.errors is None, approve.errors
    assert approve.data["approveMapping"]["adapterRunId"]

    run = _SCHEMA.execute_sync(
        "query($id:String!){ adapterRun(jobId:$id){ status branch } }",
        variable_values={"id": job_id},
        context_value=ctx,
    )
    assert run.errors is None, run.errors
    assert run.data["adapterRun"]["status"] == "DONE"


def test_test_erp_endpoint_returns_a_sample() -> None:
    ctx = _context()
    connection_id = _register_connection(ctx, erp_type="SHOPIFY", label="Shopify store")
    result = _SCHEMA.execute_sync(
        """
        mutation($conn:String!,$path:String!){
          testErpEndpoint(connectionId:$conn, path:$path){ label text error }
        }
        """,
        variable_values={"conn": connection_id, "path": "/orders"},
        context_value=ctx,
    )
    assert result.errors is None, result.errors
    # memory profile uses StubErpProbe, so a canned sample comes back with no error
    assert result.data["testErpEndpoint"]["error"] is None
    assert result.data["testErpEndpoint"]["text"]


def test_test_erp_endpoint_requires_operator_role() -> None:
    result = _SCHEMA.execute_sync(
        'mutation{ testErpEndpoint(connectionId:"conn_x"){ label } }',
        context_value=_context(roles=()),
    )
    assert result.errors
    assert "OPERATOR" in result.errors[0].message


def test_submit_without_canonical_source_errors() -> None:
    ctx = _context()
    connection_id = _register_connection(ctx, erp_type="X", label="X")
    result = _SCHEMA.execute_sync(
        """
        mutation($conn:String!,$files:[SampleFileInput!]!){
          submitMapping(connectionId:$conn, sampleFiles:$files){ jobId }
        }
        """,
        variable_values={
            "conn": connection_id,
            "files": [{"filename": "a.csv", "content": "A\n1\n"}],
        },
        context_value=ctx,
    )
    assert result.errors
