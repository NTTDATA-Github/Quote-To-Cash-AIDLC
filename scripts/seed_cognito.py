"""Create the local Floci user pool and demo users, once.

Writes `.local/cognito.env` for the api and `ui/.env` for AdminOps.
Users: demo-operator / DemoPass123! (OPERATOR), demo-reseller / DemoPass123! (reseller).
Both are tenant tnt_demo.
"""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path

import boto3

_POOL = "o2c-local"
_PASSWORD = "DemoPass123!"


def _client():
    return boto3.client(
        "cognito-idp",
        endpoint_url=os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566"),
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    )


def _pool_id(client) -> str:
    pools = client.list_user_pools(MaxResults=60)["UserPools"]
    found = next((pool for pool in pools if pool["Name"] == _POOL), None)
    if found is not None:
        return found["Id"]
    created = client.create_user_pool(
        PoolName=_POOL,
        Schema=[{"Name": "tenant_id", "AttributeDataType": "String", "Mutable": True}],
    )
    return created["UserPool"]["Id"]


def _client_id(client, pool_id: str) -> str:
    existing = client.list_user_pool_clients(UserPoolId=pool_id, MaxResults=10)["UserPoolClients"]
    named = next((item for item in existing if item["ClientName"] == "local"), None)
    if named is not None:
        return named["ClientId"]
    created = client.create_user_pool_client(
        UserPoolId=pool_id,
        ClientName="local",
        ExplicitAuthFlows=[
            "ALLOW_USER_PASSWORD_AUTH",
            "ALLOW_REFRESH_TOKEN_AUTH",
            "ALLOW_ADMIN_USER_PASSWORD_AUTH",
        ],
    )
    return created["UserPoolClient"]["ClientId"]


def _ensure_user(client, pool_id: str, username: str, group: str | None) -> None:
    try:
        client.admin_get_user(UserPoolId=pool_id, Username=username)
    except client.exceptions.UserNotFoundException:
        client.admin_create_user(
            UserPoolId=pool_id,
            Username=username,
            UserAttributes=[{"Name": "custom:tenant_id", "Value": "tnt_demo"}],
            MessageAction="SUPPRESS",
            TemporaryPassword="TempPass123!",
        )
    client.admin_set_user_password(
        UserPoolId=pool_id, Username=username, Password=_PASSWORD, Permanent=True
    )
    if group is None:
        return
    with suppress(client.exceptions.GroupExistsException):
        client.create_group(GroupName=group, UserPoolId=pool_id)
    client.admin_add_user_to_group(UserPoolId=pool_id, Username=username, GroupName=group)


def main() -> None:
    client = _client()
    pool_id = _pool_id(client)
    client_id = _client_id(client, pool_id)
    _ensure_user(client, pool_id, "demo-operator", "OPERATOR")
    _ensure_user(client, pool_id, "demo-reseller", None)

    Path(".local").mkdir(exist_ok=True)
    Path(".local/cognito.env").write_text(
        f"COGNITO_USER_POOL_ID={pool_id}\nCOGNITO_CLIENT_ID={client_id}\n", encoding="utf-8"
    )
    Path("ui/.env").write_text(
        "\n".join(
            [
                "VITE_GRAPHQL_URL=http://127.0.0.1:8000/graphql",
                "VITE_COGNITO_ENDPOINT_URL=/cognito-idp",
                "VITE_COGNITO_REGION=us-east-1",
                f"VITE_COGNITO_USER_POOL_ID={pool_id}",
                f"VITE_COGNITO_CLIENT_ID={client_id}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"cognito ready: operator and reseller, password {_PASSWORD}")


if __name__ == "__main__":
    main()
