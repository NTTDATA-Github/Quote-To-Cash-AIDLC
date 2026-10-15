# Order-to-Cash Flow: End-to-End Testing Guide

**System:** ERP & Supply Chain Order Portal  
**Version:** 0.2.0  
**Last Updated:** 2026-10-16

## Overview

This document describes the complete order-to-cash workflow, from reseller order submission through invoice delivery. It includes professional example organizations, testing steps, and integration points with NetSuite and external services.

---

## Actors & Organizations

### Resellers (Order Initiators)
- **Tech Solutions Inc.** — Primary reseller, US-based (Texas)
- **European Logistics Group** — EU reseller, multi-country operations
- **Asia Pacific Distributors Ltd.** — APAC reseller, regional hub

### Subsidiaries (Internal Fulfillment)
- **Global Supply Co.** (subsidiary of Tech Solutions Inc.) — Order fulfillment
- **Express Logistics** (subsidiary of European Logistics Group) — Shipping & delivery
- **APAC Operations Center** (subsidiary of Asia Pacific Distributors Ltd.) — Regional processing

### ERPs & External Systems
- **NetSuite** — Primary ERP for all orders, invoicing, inventory
- **Odoo** — Backup ERP (local testing)
- **Order Portal** — Web UI for resellers to submit orders

---

## Complete Order-to-Cash Flow

### Phase 1: Order Creation & Submission

```
Reseller (Tech Solutions Inc.)
    ↓
    └─→ [Order Portal] Submit Order
        - Product: Industrial Equipment (SKU: IND-500-A)
        - Quantity: 50 units
        - Delivery: Tech Solutions subsidiary "Global Supply Co."
        - Required dates: Oct 20, 2026
        ↓
    └─→ [Portal API] Create Order
        - Validate against NetSuite products
        - Create Order aggregate (domain model)
        - Publish: OrderSubmitted event
        ↓
    └─→ [Event Bus] OrderSubmitted event
        ├─→ Order Processor (order-processing role)
        ├─→ Order Projector (projections)
        └─→ Webhook Dispatcher (if webhook configured)
```

**Test Step 1: Submit Order via Portal**
```bash
curl -X POST https://o2c-staging-api.../graphql/reseller \
  -H "Authorization: Bearer <reseller-token>" \
  -d '{
    "query": "mutation { createOrder(input: { ... }) { orderId } }"
  }'
```

Expected: Order created, OrderSubmitted event published.

---

### Phase 2: Order Processing & ERP Sync

```
[Order Processor] (order-processing worker role)
    ↓
    └─→ Receive: OrderSubmitted event
        - Extract order details
        - Resolve ERP connection for Tech Solutions Inc.
        - Fetch ERP customer ID for "Global Supply Co." subsidiary
        ↓
    └─→ [NetSuite Adapter] Send Order to NetSuite
        - Create Sales Order in NetSuite
        - Set customer: Global Supply Co. (subsidiary)
        - Set delivery address: Tech Solutions warehouse (Texas)
        - Status: Pending Approval
        ↓
    └─→ [NetSuite] Sales Order Created
        - SO#: NET-2026-45892
        - ERP Order ID: NET-2026-45892
        ↓
    └─→ Record delivery status: "OrderSent to ERP"
        - Persist in Order aggregate
```

**Test Step 2: Verify ERP Sync**
```bash
# Check NetSuite for new sales order
curl -X GET https://netsuite.instance/api/v2/orders/NET-2026-45892 \
  -H "Authorization: Bearer <netsuite-token>"

# Expected: Sales Order exists with correct subsidiary mapping
```

---

### Phase 3: ERP Processing & Shipment Preparation

```
[NetSuite] (ERP operations)
    ↓
    └─→ Sales Order Workflow
        - Manager approval
        - Inventory allocation
        - Pick & pack
        - Create shipment
        ↓
    └─→ [NetSuite Webhook] Ship Event Triggered
        - Event: Shipment Created
        - Shipment ID: SHIP-NET-89234
        - Tracking: FEDEX-9872-XYZ
        - Carrier: FedEx
        ↓
    └─→ [Portal Webhook Endpoint] POST /erp/webhook/...
        - Validate webhook signature (HMAC-SHA256)
        - Parse: shipment ID, tracking, carrier
```

**Test Step 3: Simulate NetSuite Shipment Webhook**
```bash
# Send webhook to portal (test endpoint)
curl -X POST https://o2c-staging-api.../erp/webhook/netsuite-connection \
  -H "X-NetSuite-Signature: HMAC..." \
  -d '{
    "orderId": "NET-2026-45892",
    "shipmentId": "SHIP-NET-89234",
    "trackingNumber": "FEDEX-9872-XYZ",
    "carrier": "FedEx"
  }'

# Expected: Portal updates order status to "Shipped"
```

---

### Phase 4: Reseller Notification (Key Flow)

```
[Portal] OrderStatusChanged event (Shipped)
    ↓
    └─→ [Webhook Dispatcher] (webhook-dispatch role)
        ├─→ Retrieve reseller webhook config
        │   └─→ Tech Solutions Inc. webhook endpoint:
        │       https://tech-solutions.example.com/webhooks/shipments
        │
        └─→ Sign webhook payload (HMAC-SHA256)
            - Include: order_id, shipment_id, tracking, status
            - Include: timestamp, signature
            ↓
        └─→ POST to Reseller Service
            ↓
    └─→ [Tech Solutions Webhook Receiver]
        ├─→ Validate signature
        ├─→ Parse shipment details
        ├─→ Send notification to reseller admin
        │   └─→ Email: orders@tech-solutions.com
        │       Subject: "Order NET-2026-45892 Shipped - Tracking: FEDEX-9872-XYZ"
        │
        └─→ Update internal systems
            └─→ Integration with reseller's logistics platform
```

**Test Step 4: Configure & Test Reseller Webhooks**
```bash
# 1. Create webhook endpoint in portal (as reseller admin)
curl -X POST https://o2c-staging-api.../graphql/reseller \
  -H "Authorization: Bearer <reseller-token>" \
  -d '{
    "query": "mutation { 
      createWebhookEndpoint(input: {
        url: \"https://tech-solutions.example.com/webhooks/shipments\"
        secret: \"webhook-secret-key\"
        events: [\"shipment.created\", \"order.status_changed\"]
      }) { 
        endpointId 
      } 
    }"
  }'

# 2. Verify webhook delivery (check portal logs)
curl -X GET https://o2c-staging-api.../graphql/reseller \
  -H "Authorization: Bearer <reseller-token>" \
  -d '{
    "query": "{ webhookDeliveries { id status timestamp } }"
  }'

# Expected: Webhook delivered successfully to reseller service
```

---

### Phase 5: Invoice Delivery

```
[NetSuite] Invoice Workflow
    ↓
    └─→ Sales Order fulfillment complete
        - Generate invoice
        - Invoice ID: INV-NET-56123
        - Amount: $245,000 USD
        ↓
    └─→ [NetSuite Webhook] Invoice Created
        ├─→ Event type: invoice.created
        ├─→ Invoice details sent to portal
        ↓
    └─→ [Portal] InvoiceRecorded event
        ├─→ Persist invoice record
        ├─→ Update order status: "Invoiced"
        ├─→ Trigger webhook to reseller
        │   └─→ Tech Solutions Inc. receives invoice notification
        │
        └─→ [Reseller Service]
            └─→ Process invoice
                - Update accounting system
                - Send to finance team
                - Email: finance@tech-solutions.com
```

**Test Step 5: Invoice Workflow**
```bash
# Simulate invoice webhook from NetSuite
curl -X POST https://o2c-staging-api.../erp/webhook/netsuite-connection \
  -H "X-NetSuite-Signature: HMAC..." \
  -d '{
    "orderId": "NET-2026-45892",
    "invoiceId": "INV-NET-56123",
    "amount": 245000,
    "currency": "USD"
  }'

# Expected: Order marked as Invoiced, reseller notified
```

---

## NetSuite Adapter OpenAPI Specification

### Swagger/OpenAPI YAML

```yaml
openapi: 3.1.0
info:
  title: NetSuite Adapter API
  description: Order-to-Cash integration with NetSuite ERP
  version: 1.0.0
  contact:
    name: Order Portal Team

servers:
  - url: https://o2c-staging-api.../erp
    description: Production staging

paths:
  /webhook/{connection_id}:
    post:
      summary: NetSuite Webhook - Order/Invoice/Shipment Events
      description: |
        Receive events from NetSuite:
        - Sales Order created
        - Shipment prepared
        - Invoice generated
        
        Webhook must be signed with HMAC-SHA256. 
        Secret stored in portal, validated before processing.
      operationId: receiveNetSuiteWebhook
      parameters:
        - name: connection_id
          in: path
          required: true
          schema:
            type: string
            description: NetSuite connection ID (e.g., netsuite-prod-1)
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/NetSuiteWebhookPayload'
      responses:
        '200':
          description: Webhook processed successfully
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    enum: [success, processed]
                  eventId:
                    type: string
                  timestamp:
                    type: string
                    format: date-time
        '400':
          description: Invalid webhook format or signature
        '401':
          description: Signature validation failed
        '422':
          description: Validation error (unknown order, invalid data)

components:
  schemas:
    NetSuiteWebhookPayload:
      type: object
      required:
        - eventType
        - orderId
      properties:
        eventType:
          type: string
          enum: 
            - order.created
            - shipment.created
            - invoice.created
          description: Type of NetSuite event
        
        orderId:
          type: string
          description: NetSuite Sales Order ID (e.g., NET-2026-45892)
        
        shipmentId:
          type: string
          description: NetSuite Fulfillment ID (for shipment events)
        
        trackingNumber:
          type: string
          description: Carrier tracking number (e.g., FEDEX-9872-XYZ)
        
        carrier:
          type: string
          enum:
            - FedEx
            - UPS
            - DHL
            - USPS
          description: Shipping carrier
        
        invoiceId:
          type: string
          description: NetSuite Invoice ID (for invoice events)
        
        amount:
          type: number
          format: double
          description: Invoice total amount
        
        currency:
          type: string
          pattern: '^[A-Z]{3}$'
          description: ISO 4217 currency code
        
        timestamp:
          type: string
          format: date-time
          description: Event timestamp in NetSuite
        
        metadata:
          type: object
          additionalProperties: true
          description: Additional NetSuite data
      
      example:
        eventType: shipment.created
        orderId: NET-2026-45892
        shipmentId: SHIP-NET-89234
        trackingNumber: FEDEX-9872-XYZ
        carrier: FedEx
        timestamp: '2026-10-16T14:30:00Z'
```

---

## Testing Checklist

### Pre-Test Setup
- [ ] Reseller account created: "Tech Solutions Inc."
- [ ] Subsidiary configured: "Global Supply Co."
- [ ] NetSuite connection established
- [ ] Webhook endpoint configured for Tech Solutions
- [ ] Webhook secret stored securely

### Core Flow Tests
- [ ] **Test 1**: Order submission via portal ✓
- [ ] **Test 2**: Order synced to NetSuite ✓
- [ ] **Test 3**: Shipment webhook received & processed ✓
- [ ] **Test 4**: Reseller webhook triggered & delivered ✓
- [ ] **Test 5**: Invoice webhook received & processed ✓

### Integration Tests
- [ ] Webhook signature validation working
- [ ] Order status transitions correct
- [ ] Reseller notifications sent
- [ ] NetSuite data consistency maintained
- [ ] Error handling (invalid orders, signature failures)

### Performance Tests
- [ ] Webhook delivery within 2 seconds
- [ ] Order processing within 5 seconds
- [ ] Reseller notification within 30 seconds

---

## Deployment Architecture

```
┌─────────────────────────────────────────┐
│         Reseller Portal (UI)            │
│  Tech Solutions Inc. (Tenant A)         │
│  European Logistics (Tenant B)          │
└──────────────────┬──────────────────────┘
                   │
         ┌─────────┴──────────┐
         │                    │
    ┌────▼────┐          ┌────▼──────┐
    │ GraphQL │          │ HTTP/REST │
    │ (Orders)│          │ (Webhooks)│
    └────┬────┘          └────┬──────┘
         │                    │
    ┌────▼──────────────────┐ │
    │   Portal API Service  │◄┘
    │  (FastAPI + Strawberry)
    └────┬──────────────────┘
         │
    ┌────▼──────────────────────────┐
    │    Event Bus (Service Bus)     │
    │  OrderSubmitted                │
    │  OrderStatusChanged            │
    │  InvoiceRecorded               │
    └────┬──────────────────────────┘
         │
    ┌────┴─────────────────────┐
    │                          │
┌───▼────────┐        ┌────────▼──┐
│ Order      │        │ Invoice &  │
│ Processor  │        │ Delivery   │
│ (Worker)   │        │ Handler    │
└───┬────────┘        └────┬───────┘
    │                      │
    └──────────┬───────────┘
               │
        ┌──────▼────────────┐
        │  NetSuite Adapter │
        │   (Send Orders)   │
        └──────┬────────────┘
               │
        ┌──────▼──────────────────┐
        │   NetSuite ERP          │
        │  Sales Orders           │
        │  Shipments              │
        │  Invoices               │
        └──────┬──────────────────┘
               │
        ┌──────▼──────────────┐
        │ NetSuite Webhooks   │
        │ (Events back to API)│
        └──────┬──────────────┘
               │
        ┌──────▼────────────────┐
        │ Reseller Webhooks     │
        │ (Notifications)       │
        └──────────────────────┘
```

---

## Support & Monitoring

**API Health:** https://o2c-staging-api.../livez  
**Swagger UI:** https://o2c-staging-api.../docs  
**Metrics:** https://o2c-staging-api.../metrics

**Contacts:**
- Portal Team: portal-team@company.com
- NetSuite Admin: netsuite-admin@company.com
- Reseller Support: reseller-support@company.com

---

**End of Document**
