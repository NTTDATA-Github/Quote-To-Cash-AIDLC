#!/bin/bash
# Complete ERP setup flow: Register NetSuite + Distributor + Reseller + Webhooks
# Usage: ./test_erp_flow.sh [BEARER_TOKEN]
#
# Steps:
# 1. Register NetSuite ERP connection
# 2. Create Distributor (Subsidiary)
# 3. Connect Distributor to ERP
# 4. Create Reseller Binding
# 5. Register Webhook for Order Notifications

set -e

API_URL="https://o2c-staging-api.calmgrass-bdb2a764.eastus.azurecontainerapps.io"
OPERATOR_ENDPOINT="$API_URL/graphql/operator"
RESELLER_ENDPOINT="$API_URL/graphql/reseller"
TOKEN="${1:-your_bearer_token_here}"

if [ "$TOKEN" = "your_bearer_token_here" ]; then
  echo "❌ Error: Please provide a bearer token as argument"
  echo "Usage: $0 <bearer_token>"
  echo ""
  echo "To get a token, authenticate with Keycloak:"
  echo "  curl -X POST https://o2c-staging-keycloak.../realms/o2c/protocol/openid-connect/token \\"
  echo "    -d 'client_id=o2c-portal&username=operator1&password=<password>&grant_type=password'"
  exit 1
fi

echo "=========================================="
echo "ERP SETUP FLOW: NetSuite + Distributor + Reseller + Webhooks"
echo "=========================================="

# ============================================
# 1. REGISTER NETSUITE ERP
# ============================================
echo ""
echo "1️⃣ REGISTERING NETSUITE ERP..."

CONNECTION_ID=$(curl -s -X POST "$OPERATOR_ENDPOINT" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "query": "mutation RegisterConnection($erpType: String!, $instanceLabel: String!, $baseUrl: String!, $credentials: JSON!, $auth: AuthConfigInput!) { registerConnection(erpType: $erpType, instanceLabel: $instanceLabel, baseUrl: $baseUrl, credentials: $credentials, auth: $auth) { connectionId erpType instanceLabel status } }",
    "variables": {
      "erpType": "netsuite",
      "instanceLabel": "NetSuite Staging",
      "baseUrl": "https://o2c-staging-mock-netsuite.calmgrass-bdb2a764.eastus.azurecontainerapps.io",
      "credentials": {"account_id": "TSTDRV123"},
      "auth": {
        "authType": "oauth_1_0a",
        "params": {"consumer_key": "ck_demo", "token_id": "ti_demo"},
        "secret": "cs_demo|ts_demo"
      }
    }
  }' | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('data',{}).get('registerConnection',{}).get('connectionId',''))" 2>/dev/null)

if [ -z "$CONNECTION_ID" ]; then
  echo "❌ Failed to register NetSuite"
  exit 1
fi

echo "✅ NetSuite registered: $CONNECTION_ID"

# ============================================
# 2. CREATE DISTRIBUTOR (SUBSIDIARY)
# ============================================
echo ""
echo "2️⃣ CREATING DISTRIBUTOR..."

SUBSIDIARY_ID=$(curl -s -X POST "$OPERATOR_ENDPOINT" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "query": "mutation CreateSubsidiary($name: String!, $country: String!, $language: String!) { createSubsidiary(name: $name, country: $country, language: $language) { subsidiaryId name } }",
    "variables": {
      "name": "Global Supply Co.",
      "country": "US",
      "language": "en"
    }
  }' | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('data',{}).get('createSubsidiary',{}).get('subsidiaryId',''))" 2>/dev/null)

if [ -z "$SUBSIDIARY_ID" ]; then
  echo "❌ Failed to create subsidiary"
  exit 1
fi

echo "✅ Distributor created: $SUBSIDIARY_ID"

# ============================================
# 3. CONNECT DISTRIBUTOR TO ERP
# ============================================
echo ""
echo "3️⃣ ROUTING DISTRIBUTOR TO NETSUITE..."

curl -s -X POST "$OPERATOR_ENDPOINT" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{
    \"query\": \"mutation SetErpRoute(\\\$subsidiaryId: String!, \\\$connectionId: String!, \\\$erpCompanyId: String!) { setErpRoute(subsidiaryId: \\\$subsidiaryId, connectionId: \\\$connectionId, erpCompanyId: \\\$erpCompanyId) { subsidiaryId erpRoute { connectionId erpCompanyId } } }\",
    \"variables\": {
      \"subsidiaryId\": \"$SUBSIDIARY_ID\",
      \"connectionId\": \"$CONNECTION_ID\",
      \"erpCompanyId\": \"NS1\"
    }
  }" > /dev/null

echo "✅ Distributor routed to NetSuite (Connection: $CONNECTION_ID, Company: NS1)"

# ============================================
# 4. CREATE RESELLER BINDING
# ============================================
echo ""
echo "4️⃣ CREATING RESELLER BINDING..."

BINDING_ID=$(curl -s -X POST "$OPERATOR_ENDPOINT" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{
    \"query\": \"mutation CreateBinding(\\\$tenantId: String!, \\\$connectionId: String!, \\\$erpCustomerId: String!, \\\$name: String!) { createBinding(tenantId: \\\$tenantId, connectionId: \\\$connectionId, erpCustomerId: \\\$erpCustomerId, name: \\\$name) { bindingId tenantId status } }\",
    \"variables\": {
      \"tenantId\": \"tnt_tech_solutions\",
      \"connectionId\": \"$CONNECTION_ID\",
      \"erpCustomerId\": \"101\",
      \"name\": \"Tech Solutions Inc.\"
    }
  }" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('data',{}).get('createBinding',{}).get('bindingId',''))" 2>/dev/null)

if [ -z "$BINDING_ID" ]; then
  echo "❌ Failed to create binding"
  exit 1
fi

echo "✅ Reseller binding created: $BINDING_ID"

# ============================================
# 5. REGISTER WEBHOOK ENDPOINT
# ============================================
echo ""
echo "5️⃣ REGISTERING WEBHOOK ENDPOINT..."

WEBHOOK_RESPONSE=$(curl -s -X POST "$RESELLER_ENDPOINT" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "query": "mutation RegisterWebhookEndpoint($name: String!, $url: String!, $eventTypes: [String!]) { registerWebhookEndpoint(name: $name, url: $url, eventTypes: $eventTypes) { endpoint { endpointId name url eventTypes isActive } signingSecret } }",
    "variables": {
      "name": "Tech Solutions Webhook",
      "url": "https://tech-solutions.example.com/webhooks/orders",
      "eventTypes": ["order.submitted", "shipment.recorded", "invoice.created"]
    }
  }')

ENDPOINT_ID=$(echo "$WEBHOOK_RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('data',{}).get('registerWebhookEndpoint',{}).get('endpoint',{}).get('endpointId',''))" 2>/dev/null)
SIGNING_SECRET=$(echo "$WEBHOOK_RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('data',{}).get('registerWebhookEndpoint',{}).get('signingSecret',''))" 2>/dev/null)

if [ -z "$ENDPOINT_ID" ]; then
  echo "❌ Failed to register webhook"
  exit 1
fi

echo "✅ Webhook endpoint registered: $ENDPOINT_ID"
echo "   Signing Secret: $SIGNING_SECRET"

# ============================================
# SUMMARY
# ============================================
echo ""
echo "=========================================="
echo "✅ COMPLETE FLOW SETUP SUCCESSFUL!"
echo "=========================================="
echo ""
echo "Summary:"
echo "  ERP Connection ID: $CONNECTION_ID"
echo "  Distributor ID:   $SUBSIDIARY_ID"
echo "  Reseller Binding: $BINDING_ID"
echo "  Webhook Endpoint: $ENDPOINT_ID"
echo ""
echo "Ready for order-to-cash flow testing!"
echo ""
echo "Next steps:"
echo "1. Use the API to create orders"
echo "2. Orders will flow through: API → NetSuite Mock → Reseller Webhook"
echo "3. Check webhook deliveries in Operator dashboard"
