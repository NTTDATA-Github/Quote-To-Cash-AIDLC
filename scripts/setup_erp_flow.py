#!/usr/bin/env python3
"""
End-to-end setup: Register NetSuite ERP, create distributor, reseller, and webhooks.
Usage: python scripts/setup_erp_flow.py [--api-url https://...] [--token ...]
"""

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# Ignore SSL for local testing
ssl._create_default_https_context = ssl._create_unverified_context


class GraphQLClient:
    def __init__(self, api_url: str, token: str):
        self.api_url = api_url
        self.token = token

    def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute GraphQL query/mutation."""
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        req = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            raise Exception(f"HTTP {e.code}: {body}") from e


def register_netsuite_erp(client: GraphQLClient) -> dict[str, Any]:
    """1. Register NetSuite ERP connection."""
    print("\n=== 1. REGISTERING NETSUITE ERP ===")

    mutation = """
    mutation RegisterConnection(
        $erpType: String!
        $instanceLabel: String!
        $baseUrl: String!
        $credentials: JSON!
        $auth: AuthConfigInput!
        $webhookSecretRef: String
    ) {
        registerConnection(
            erpType: $erpType
            instanceLabel: $instanceLabel
            baseUrl: $baseUrl
            credentials: $credentials
            auth: $auth
            webhookSecretRef: $webhookSecretRef
        ) {
            connectionId
            erpType
            instanceLabel
            baseUrl
            status
        }
    }
    """

    variables = {
        "erpType": "netsuite",
        "instanceLabel": "NetSuite Staging",
        "baseUrl": "https://o2c-staging-mock-netsuite.calmgrass-bdb2a764.eastus.azurecontainerapps.io",
        "credentials": {
            "account_id": "TSTDRV123",
        },
        "auth": {
            # authType only gates the generic onboarding probe for connections with no
            # adapter yet (src/modules/reference/connections/application/service.py);
            # NetSuite has a real adapter, and "oauth_1_0a" isn't a member of AuthType
            # (NONE/API_KEY_HEADER/BASIC/BEARER_TOKEN), so registerConnection rejects it.
            "authType": "NONE",
            "params": {
                "consumer_key": "ck_demo",
                "token_id": "ti_demo",
            },
            # The NetSuite adapter reads this as JSON ({"consumer_secret", "token_secret"}
            # — see netsuite_adapter.py's _credentials()), not the pipe-separated format.
            "secret": json.dumps({"consumer_secret": "cs_demo", "token_secret": "ts_demo"}),
        },
        "webhookSecretRef": "netsuite-webhook-secret",
    }

    result = client.query(mutation, variables)
    if "errors" in result:
        raise Exception(f"Registration failed: {result['errors']}")

    connection = result["data"]["registerConnection"]
    print("✅ NetSuite registered:")
    print(f"   Connection ID: {connection['connectionId']}")
    print(f"   Type: {connection['erpType']}")
    print(f"   Label: {connection['instanceLabel']}")
    print(f"   Status: {connection['status']}")

    return connection


def create_subsidiary(client: GraphQLClient) -> dict[str, Any]:
    """2. Create a distributor (subsidiary)."""
    print("\n=== 2. CREATING DISTRIBUTOR (SUBSIDIARY) ===")

    mutation = """
    mutation CreateSubsidiary($name: String!, $country: String!, $language: String!) {
        createSubsidiary(name: $name, country: $country, language: $language) {
            subsidiaryId
            name
            country
            language
        }
    }
    """

    variables = {
        "name": "Global Supply Co.",
        "country": "US",
        "language": "en",
    }

    result = client.query(mutation, variables)
    if "errors" in result:
        raise Exception(f"Subsidiary creation failed: {result['errors']}")

    subsidiary = result["data"]["createSubsidiary"]
    print("✅ Distributor created:")
    print(f"   Subsidiary ID: {subsidiary['subsidiaryId']}")
    print(f"   Name: {subsidiary['name']}")
    print(f"   Country: {subsidiary['country']}")

    return subsidiary


def set_erp_route(client: GraphQLClient, subsidiary_id: str, connection_id: str) -> dict[str, Any]:
    """3. Connect subsidiary to ERP."""
    print("\n=== 3. ROUTING DISTRIBUTOR TO NETSUITE ===")

    mutation = """
    mutation SetErpRoute($subsidiaryId: String!, $connectionId: String!, $erpCompanyId: String!) {
        setErpRoute(
            subsidiaryId: $subsidiaryId
            connectionId: $connectionId
            erpCompanyId: $erpCompanyId
        ) {
            subsidiaryId
            name
        }
    }
    """

    variables = {
        "subsidiaryId": subsidiary_id,
        "connectionId": connection_id,
        "erpCompanyId": "NS1",  # NetSuite company ID
    }

    result = client.query(mutation, variables)
    if "errors" in result:
        raise Exception(f"ERP route failed: {result['errors']}")

    # setErpRoute returns the Subsidiary itself (no nested erpRoute field) — confirm the
    # route with the separate top-level `erpRoute(subsidiaryId: ...)` query instead.
    subsidiary = result["data"]["setErpRoute"]
    route_query = """
    query ErpRoute($subsidiaryId: String!) {
        erpRoute(subsidiaryId: $subsidiaryId) {
            connectionId
            erpCompanyId
        }
    }
    """
    route_result = client.query(route_query, {"subsidiaryId": subsidiary_id})
    route = route_result.get("data", {}).get("erpRoute") or {}

    print("✅ Distributor routed to ERP:")
    print(f"   Subsidiary: {subsidiary['subsidiaryId']}")
    print(f"   ERP Connection: {route.get('connectionId')}")
    print(f"   ERP Company ID: {route.get('erpCompanyId')}")

    return subsidiary


def create_reseller_binding(
    client: GraphQLClient, connection_id: str, tenant_id: str
) -> dict[str, Any]:
    """4. Create binding (reseller linked to ERP)."""
    print("\n=== 4. CREATING RESELLER BINDING ===")

    mutation = """
    mutation CreateBinding(
        $tenantId: String!
        $connectionId: String!
        $erpCustomerId: String!
        $name: String!
    ) {
        createBinding(
            tenantId: $tenantId
            connectionId: $connectionId
            erpCustomerId: $erpCustomerId
            name: $name
        ) {
            bindingId
            tenantId
            connectionId
            erpCustomerId
            status
        }
    }
    """

    variables = {
        "tenantId": tenant_id,
        "connectionId": connection_id,
        "erpCustomerId": "101",  # NetSuite customer ID
        "name": "Tech Solutions Inc.",
    }

    result = client.query(mutation, variables)
    if "errors" in result:
        raise Exception(f"Binding creation failed: {result['errors']}")

    binding = result["data"]["createBinding"]
    print("✅ Reseller binding created:")
    print(f"   Binding ID: {binding['bindingId']}")
    print(f"   Tenant ID: {binding['tenantId']}")
    print(f"   ERP Customer: {binding['erpCustomerId']}")
    print(f"   Status: {binding['status']}")

    return binding


def register_webhook_endpoint(client: GraphQLClient, tenant_token: str) -> dict[str, Any]:
    """5. Register webhook endpoint for reseller notifications."""
    print("\n=== 5. REGISTERING WEBHOOK ENDPOINT ===")

    # Use reseller-scoped token
    reseller_client = GraphQLClient(
        client.api_url.replace("/graphql/operator", "/graphql/reseller"),
        tenant_token,
    )

    mutation = """
    mutation RegisterWebhookEndpoint(
        $name: String!
        $url: String!
        $eventTypes: [String!]
    ) {
        registerWebhookEndpoint(name: $name, url: $url, eventTypes: $eventTypes) {
            endpoint {
                endpointId
                name
                url
                eventTypes
                isActive
            }
            signingSecret
        }
    }
    """

    variables = {
        "name": "Tech Solutions Webhook",
        # tech-solutions.example.com isn't a real endpoint — deliveries there would just
        # time out silently. mock-reseller is the deployed dev aid built to watch them
        # (infra/azure/modules/mocks, terraform output `mock_reseller_url`).
        "url": "https://o2c-staging-mock-reseller.calmgrass-bdb2a764.eastus.azurecontainerapps.io/hooks",
        "eventTypes": ["order.submitted", "shipment.recorded", "invoice.created"],
    }

    result = reseller_client.query(mutation, variables)
    if "errors" in result:
        raise Exception(f"Webhook registration failed: {result['errors']}")

    webhook_response = result["data"]["registerWebhookEndpoint"]
    endpoint = webhook_response["endpoint"]
    signing_secret = webhook_response["signingSecret"]

    print("✅ Webhook endpoint registered:")
    print(f"   Endpoint ID: {endpoint['endpointId']}")
    print(f"   Name: {endpoint['name']}")
    print(f"   URL: {endpoint['url']}")
    print(f"   Event Types: {endpoint['eventTypes']}")
    print(f"   Active: {endpoint['isActive']}")
    print(f"   Signing Secret: {signing_secret}")

    return {
        "endpoint": endpoint,
        "signing_secret": signing_secret,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Setup ERP flow: NetSuite + Distributor + Reseller + Webhooks"
    )
    parser.add_argument(
        "--api-url",
        default="https://o2c-staging-api.calmgrass-bdb2a764.eastus.azurecontainerapps.io/graphql/operator",
        help="Operator API endpoint",
    )
    parser.add_argument(
        "--token",
        default="operator1_token",
        help="Bearer token for API (or will use Keycloak to get one)",
    )
    parser.add_argument(
        "--tenant-id",
        default="tnt_demo",  # the only real tenant in the staging Keycloak realm (operator1)
        help="Reseller tenant ID",
    )
    parser.add_argument(
        "--tenant-token",
        default="reseller_token",
        help="Reseller bearer token for webhook registration",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("ERP FLOW SETUP: NetSuite + Distributor + Reseller + Webhooks")
    print("=" * 60)

    # Initialize client
    client = GraphQLClient(args.api_url, args.token)

    try:
        # 1. Register NetSuite ERP
        connection = register_netsuite_erp(client)
        connection_id = connection["connectionId"]

        # 2. Create Distributor (Subsidiary)
        subsidiary = create_subsidiary(client)
        subsidiary_id = subsidiary["subsidiaryId"]

        # 3. Route Distributor to ERP
        set_erp_route(client, subsidiary_id, connection_id)

        # 4. Create Reseller Binding
        binding = create_reseller_binding(client, connection_id, args.tenant_id)

        # 5. Register Webhook for Reseller
        webhook = register_webhook_endpoint(client, args.tenant_token)

        # Summary
        print("\n" + "=" * 60)
        print("✅ COMPLETE FLOW SETUP SUCCESSFUL!")
        print("=" * 60)
        print("\nSetup Summary:")
        print(f"  ERP Connection: {connection_id}")
        print(f"  Distributor: {subsidiary_id}")
        print(f"  Reseller Binding: {binding['bindingId']}")
        print(f"  Webhook Endpoint: {webhook['endpoint']['endpointId']}")
        print("\nReady for order-to-cash flow testing!")

        return 0

    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
