# Test the whole order in Odoo and AdminOps

AdminOps does not create the sales order. Sales writes it in Odoo. A worker then reads it about every 30 seconds: first the quotation, then confirmation, then the delivery, then the invoice.

Two kinds of work are on this page.

- **Setup.** Do it once. Check whether it is already there before you change anything. `bash scripts/local.sh up` already registers the connection, the reseller binding, and the subsidiary, and this Odoo database already has the customer and the product.
- **The order.** Do this each time you want a new test. A second test is a new quotation. Do not edit the closed one.

Use the customer and product below. A quotation for any other customer, or any other company, stays in Odoo and never appears in AdminOps.

## Sign-in

| | |
|---|---|
| Odoo | http://127.0.0.1:8069 — `admin` / `admin`, database `odoo` |
| AdminOps | http://127.0.0.1:5173 — `demo-operator` / `DemoPass123!` |

---

## Setup — check these first

Each block says why it exists, how to see that it is already done, and what to do only when it is missing.

### 1. The stack is running

**When:** every time you sit down, not a data change.

**Why:** AdminOps only shows an order after the API and the worker have read Odoo. If either process is stopped, the quotation stays in Odoo.

**Check first:**

- http://127.0.0.1:8000/livez answers.
- http://127.0.0.1:8069/web/login shows the Odoo login.
- http://127.0.0.1:5173 shows AdminOps.

**If those pages open:** do nothing.

**If they do not:** `bash scripts/local.sh up`. That starts Odoo, Keycloak, the API, the mocks, and AdminOps. The API reseeds the demo on each start.

### 2. Connection, reseller, and subsidiary

**When:** once. The seed creates them. Do not create a second copy if these rows are already on screen.

**Why:** the worker only reads customers that have a **verified** binding, and it only keeps the order when the quotation’s company id is the company recorded on the subsidiary. Without those three rows there is nothing to match.

**Check first.** Sign in to AdminOps as `demo-operator`.

| Screen | Already set up when you see |
|---|---|
| **ERP connections** | `conn_odoo_local`, label **Local Odoo (dev)**, type Odoo, status ACTIVE, URL `http://localhost:8069` |
| **Resellers** | binding `bind_demo`, tenant `tnt_demo`, connection `conn_odoo_local`, ERP customer id **`1`**, status VERIFIED |
| **Subsidiaries** | `sub_demo`, name **Demo subsidiary**, country US, connection `conn_odoo_local`, Odoo company id **`1`** |

**If all three match:** leave them. Creating another binding for the same connection, or another subsidiary on `conn_odoo_local`, is rejected. One connection belongs to one subsidiary.

**If a row is missing:** run `bash scripts/local.sh up` again. The seed puts them back. You do not type them in by hand for this demo.

The customer id **`1`** is the whole point of the next step. The worker asks Odoo for sales orders whose customer is partner `1`. It does not search by name.

### 3. The customer the binding follows

**When:** once. This contact is created with the Odoo database. Do not create a new contact for the test.

**Why:** the binding stores an id, not a name. Two contacts can both be called something like “YourCompany.” Only the one whose URL contains `id=1` is read.

**Check first:**

1. In Odoo, **Settings → Activate the developer mode** if you do not already see a **Deactivate the developer mode** item. Developer mode is per browser. It only lets you see the id. It does not change data.
2. **Contacts**. Open **YourCompany**.
3. The address bar must contain `id=1`.

| Field | Value on id 1 |
|---|---|
| Name | **YourCompany** |
| Email | info@yourcompany.com |
| Phone | +1 555-555-5556 |
| Street | 250 Executive Park Blvd, Suite 3400 |
| City | San Francisco |
| Country | United States |

**If that record is id 1:** use it as the customer on the quotation. Do not edit the address.

**If you opened a different id:** close it and open the contact whose URL says `id=1`. These contacts exist and are **not** followed unless you change the binding:

| Name | Odoo id | Already in Odoo |
|---|---|---|
| Acme Corporation | 10 | `S00036`, confirmed |
| Gemini Furniture | 11 | `S00016`, confirmed |
| Azure Interior | 14 | — |

Leave them. An order for Acme stays invisible while the binding says `1`.

### 4. The company on the quotation

**When:** once. A new database has one company.

**Why:** the subsidiary `sub_demo` is tied to Odoo company id **`1`**. The worker drops a quotation whose company id is anything else, even when the customer is correct.

**Check first:** **Settings → Companies → YourCompany**. With developer mode on, the URL contains `id=1`. Currency is USD.

**If that is what you see:** you usually never touch the company field on the quotation. Odoo fills **YourCompany** in for you.

**If a second company exists:** on the quotation, set the company to **YourCompany** before you save.

### 5. Sales and Invoicing

**When:** once per Odoo database.

**Why:** the quotation and the customer invoice are screens from these apps. The worker reads `sale.order` and posted `account.move` documents. It does not install the apps.

**Check first:** **Apps**, remove the **Apps** filter so installed modules show, and search.

| App | On this database |
|---|---|
| Sales | Already installed |
| Invoicing | Already installed |

**If the button says Installed:** do nothing.

**If it says Install:** install it and wait until the button changes. Then continue.

### 6. Inventory

**When:** once per Odoo database, and **before** you confirm the quotation you want to deliver.

**Why:** confirming a sales order creates a delivery only when Inventory is installed. The worker reads a done `stock.picking`. Without that app there is no Delivery button, so the delivered quantity in AdminOps stays 0 even though the order can still be confirmed and invoiced.

**Check first:** **Apps**, search **Inventory**.

**If it says Installed:** skip this step.

**If it says Install:** install it and wait until it finishes. A sales order you already confirmed **before** this install has no delivery. Leave that order. Create a new quotation after the install.

### 7. The product and its Internal Reference

**When:** once per product. This one is already filled in. Do not create a second product, and do not clear the reference.

**Why:** Odoo’s product name is not what we store. The worker keeps a line only when the product’s **Internal Reference** (`default_code`) is set, and the quantity is above zero. A line without a reference is skipped. An order whose lines are all skipped is not adopted.

**Check first:** **Sales → Products → Products**, open **Office Chair Black**.

| Field | Must be |
|---|---|
| Name | Office Chair Black |
| Internal Reference | **FURN_0269** |
| Sales price | **120.50** |
| Unit | Units |
| Product type | Goods |

**If Internal Reference is `FURN_0269`:** close the product. You will put this product on the quotation.

**If Internal Reference is empty:** type `FURN_0269`, save, and do not change it again. Only then create the quotation.

---

## The order — every test

Do these on a **new** quotation. Confirm, deliver, and invoice that same document. Wait about 30 seconds after each save. The worker is on a timer. Refreshing AdminOps faster than that will still show the previous status.

### 8. Create the quotation

**When:** every test.

**Why:** this is the document the worker adopts. Saving it is enough. You do not confirm it yet. A draft is stored as `SENT_TO_ERP`, which means “we have seen this sales order,” not “Odoo has confirmed it.”

1. **Sales → Orders → Quotations → New.**
2. **Customer:** **YourCompany**, the contact from step 3 (`id=1`).
3. **Customer Reference:** `TEST-PO-001`. On Odoo 17 this is on the **Other Info** tab when it is not beside the customer. AdminOps shows it as the order reference. Blank means the reference becomes the `S00…` number instead.
4. **Order Lines → Add a product:** **Office Chair Black**.
5. Check the line matches this, then **Save**:

| Column | Value |
|---|---|
| Product | Office Chair Black |
| Internal Reference behind it | FURN_0269 |
| Quantity | **2** |
| Unit price | **120.50** |
| Taxes | leave what Odoo fills in |
| Untaxed amount | **241.00** |

6. Company is **YourCompany** (step 4). Save.
7. Write down the number at the top, such as `S00042`. Below, that number is `S00…`. The document is still a **Quotation**.

### 9. See it in AdminOps

**When:** every test, after the save.

**Why:** this proves the binding, the company, and the Internal Reference all matched. If this row never appears, later clicks in Odoo will not show up either.

Wait up to 30 seconds. In AdminOps open **Orders**.

| Column | Value |
|---|---|
| Order id | `ord_conn_odoo_local_S00…` |
| Reseller | `tnt_demo` |
| Reference | `TEST-PO-001` |
| ERP order | `S00…` |
| Status | `SENT_TO_ERP` |
| Subsidiary | `sub_demo` |
| Product | `FURN_0269` |
| Quantity | 2 |
| Unit price | 120.50 USD |
| Delivered / invoiced | 0 / 0 |

**Notifications** stays empty. A row appears there only after a webhook was sent to a reseller endpoint. The seed does not create an endpoint. The order still moves.

**If the order is missing after a minute:** the customer was not id `1`, the Internal Reference was empty, or the company was not id `1`. Fix that on a new quotation. Do not keep refreshing the same wrong one.

### 10. Confirm

**When:** every test, on this quotation.

**Why:** confirmation is the sales order. Odoo sets `state` to `sale`. The next read maps that to **`CONFIRMED`**. A draft or a sent quotation does not.

Click **Confirm**. Odoo renames the document from Quotation to Sales Order. Wait for the next sweep. AdminOps status becomes **`CONFIRMED`**. Quantity stays 2. Delivered and invoiced stay 0.

### 11. Deliver

**When:** every test, after confirm, and only if Inventory was installed **before** this confirm (step 6).

**Why:** AdminOps does not treat “confirmed” as “delivered.” It adds the delivered quantity only from a warehouse transfer whose state is **Done**. A waiting or ready transfer is ignored. The transfer’s number is the proof of delivery.

1. On the sales order, open the **Delivery** smart button. The number looks like `WH/OUT/00001`.
2. The demand is **2** of Office Chair Black.
3. **Validate**. If Odoo asks about an immediate transfer, accept it.
4. The transfer’s status must be **Done**.

Wait for the next sweep. AdminOps stays **`CONFIRMED`**. Delivered quantity on `FURN_0269` becomes **2**. The sweep after that does not add another 2.

No Delivery button means Inventory was missing at confirm time. Install it (step 6) and start a new quotation. This order can still be invoiced, but its delivered quantity will stay 0.

### 12. Invoice

**When:** every test, after the delivery if you want both quantities on this order.

**Why:** a posted customer invoice is what closes the order. The worker reads a posted `out_invoice` and sets the invoiced quantity from its lines. A draft invoice is ignored. A credit note is ignored. Odoo’s invoice status becomes “fully invoiced,” which we store as **`CLOSED`**.

1. On the sales order, **Create Invoice**.
2. Leave it a regular invoice. **Create and View Invoice**.
3. The line is Office Chair Black, quantity **2**, price **120.50**.
4. **Confirm**. The invoice must say **Posted**.
5. Open the sales order again. Invoice status is **Fully invoiced**.

Wait for the next sweep. AdminOps becomes **`CLOSED`**. Invoiced quantity becomes **2**. Delivered quantity stays **2**. Another 30 seconds does not increase either number.

You can post the invoice before the delivery. The order still closes, and the delivered quantity stays 0. Do step 11 first when you want both.

### 13. Cancel — a different order

**When:** only when you want to see a cancel. Not part of the happy path.

**Why:** cancelling this order stops the delivery and invoice test. Odoo `state=cancel` is stored as **`CANCELLED`**.

Create another quotation with the same customer and product, save it, wait until AdminOps shows it, then **Cancel** in Odoo. The closed order from step 12 stays `CLOSED`.

---

## What each Odoo action becomes

| You do this | Odoo | AdminOps | How often |
|---|---|---|---|
| Save the quotation | `state=draft` | `SENT_TO_ERP` | Every test |
| Confirm | `state=sale` | `CONFIRMED` | Every test |
| Validate the delivery | picking `state=done` | stays `CONFIRMED`, delivered qty **2** | Every test |
| Post the invoice | invoice `posted`, `invoice_status=invoiced` | `CLOSED`, invoiced qty **2** | Every test |
| Cancel a different order | `state=cancel` | `CANCELLED` | Only if you want to see a cancel |

## Optional, and also one-time: a webhook

**Why:** the 30-second read is enough for every step above. An Automation Rule lets Odoo push a status change sooner. Deliveries and invoice lines are still read by the poll. The rule does not replace it.

**Check first:** **Settings → Technical → Automation → Automation Rules**, model Sales Order. If a rule already posts to the URL below, leave it.

**If there is no such rule:** add one using [webhook.md](./webhook.md). The URL from inside the Odoo container is:

```
http://host.docker.internal:8000/erp/webhook/conn_odoo_local/odoo-webhook-demo
```

The secret `odoo-webhook-demo` is already stored for `conn_odoo_local`. Do not create a new one.

## Done when

- AdminOps **Orders** has `ord_conn_odoo_local_S00…` for reseller `tnt_demo`.
- Reference is `TEST-PO-001`, ERP order is your `S00…` number, product is `FURN_0269`, quantity is 2.
- Status is `CLOSED`.
- Delivered quantity is 2 and invoiced quantity is 2.
- Waiting another 30 seconds does not increase those quantities.
