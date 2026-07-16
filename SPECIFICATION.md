# Open Ledger Protocol (OLP) Specification
**Version 1.0.0-draft**

The **Open Ledger Protocol (OLP)** defines a standardized, metadata-driven system for financial accounting integrations. By decoupling business event creation from ledger compilation, OLP allows commerce/checkout platforms to send generic transaction events, which are dynamically mapped to double-entry ledger entries.

---

## 1. Accounting Context Headers

Every OLP-compliant payload contains an `accounting_context` block. This block acts as the routing header for the double-entry compiler.

| Header Field | Type | Allowed Values | Description |
| :--- | :--- | :--- | :--- |
| `entity_id` | String | e.g. `"acme_us"`, `"acme_de"`| Identifies the primary billing legal entity (subsidiary) responsible for the sale. |
| `role` | String | `"principal"`, `"agent"` | Determines if the business sells as a principal (gross revenue) or as an agent (net commission). |
| `product_type` | String | `"physical"`, `"digital_saas"`, `"digital_download"` | Determines the nature of the product and cost implications. |
| `recognition` | String | `"point_in_time"`, `"over_time"` | Dictates whether revenue is recognized immediately or ratably over a term. |
| `term_months` | Integer | >= 1 | Required if `recognition` is `"over_time"`. The amortization period in months. |
| `payment_method`| String | `"card"`, `"invoice"` | Determines debit side asset routing (Cash/Card Clearing vs. Accounts Receivable). |
| `billing_status`| String | `"billed"`, `"unbilled"` | Determines asset routing for unbilled work (Accounts Receivable vs. Contract Assets). |

---

## 2. Event Payload Schema

A standard OLP event payload contains transactional details, metadata routing headers, a required idempotency key, and monetary adjustments. 

> [!IMPORTANT]
> **Minor Currency Units (Integers)**: All money values in OLP v1.0 must be represented as integers in their minor currency units (e.g., $120.00 is represented as `12000` cents). This eliminates floating-point rounding errors.

```json
{
  "event_id": "evt_100293",
  "event_type": "payment_received", // ["payment_received" | "fulfillment_completed" | "immediate_sale" | "payment_settled" | "refund_issued" | "goods_returned" | "contract_billed" | "invoice_written_off" | "order_placed" | "charge_settled" | "payout_cleared"]
  "timestamp": "2026-07-16T08:00:00Z",
  "idempotency_key": "idemp-9a8b7c6d-5e4f-3a2b", // Required to prevent double-posting
  "amount": 12000,                  // Gross amount in cents (inclusive of tax)
  "currency": "USD",
  "description": "Premium Subscription Annual Plan",
  "customer_id": "cust_8829",
  "tax_amount": 1000,               // Taxes included in the amount ($10.00 represented as 1000)
  "tax_jurisdiction": "DE",         // Country/state code for local tax credit segregation (e.g. "DE" or "US-CA")
  "processing_fee": 380,            // Merchant gateway fee ($3.80 represented as 380)
  "discount_amount": 2000,          // Transaction discount ($20.00 represented as 2000)
  "capitalized_costs": 1200,        // Capitalized contract commissions (ASC 340-40, e.g. $12.00 = 1200)
  "functional_amount": 12000,       // local currency equivalent at settlement (ASC 830)
  "intercompany_entity_id": "acme_us", // Partner entity providing services (ASC 810)
  "intercompany_transfer_amount": 8500, // Transfer pricing fee to route to partner books ($85.00 = 8500)
  "accounting_context": {
    "entity_id": "acme_de",
    "role": "principal",
    "product_type": "digital_saas",
    "recognition": "over_time",
    "term_months": 12,
    "payment_method": "card",
    "billing_status": "billed"
  },
  "line_items": [
    {
      "item_id": "prod_premium_annual",
      "price": 12000,
      "cogs_estimate": 0
    }
  ]
}
```

---

## 3. Account Hierarchies (Chart of Accounts)

In OLP, flat account names are replaced by standardized hierarchical paths. This enables seamless integration with ledger engines like Twisp and Fragment that compile parent-child balances.

| Standard Accounting Term | OLP Standardized Account Path |
| :--- | :--- |
| **Cash** | `/assets/liquid/cash` |
| **Accounts Receivable** | `/assets/receivables/ar` |
| **Contract Assets (Unbilled AR)** | `/assets/receivables/contract_assets` |
| **Order Clearing Account** | `/assets/receivables/order_clearing` |
| **Payment Clearing Account** | `/assets/receivables/payment_clearing` |
| **Intercompany Receivable** | `/assets/receivables/intercompany_<subsidiary_id>` |
| **Inventory** | `/assets/inventory` |
| **Deferred Contract Costs (Assets)** | `/assets/deferred_costs/commissions` |
| **Deferred Revenue** | `/liabilities/deferred/revenue` |
| **Deferred Payable (Vendor)** | `/liabilities/deferred/payable_vendor` |
| **Deferred Commission Revenue**| `/liabilities/deferred/commission` |
| **Accounts Payable (Vendor)** | `/liabilities/payables/vendor` |
| **Sales Tax Payable (Global)** | `/liabilities/tax/payable` |
| **Sales Tax Payable (Local)** | `/liabilities/tax/payable/<jurisdiction_id>` |
| **Commissions Payable** | `/liabilities/payables/commissions` |
| **Intercompany Payable** | `/liabilities/payables/intercompany_<subsidiary_id>` |
| **Gross Revenue** | `/equity/revenue/gross` |
| **Subscription Revenue** | `/equity/revenue/subscription` |
| **Commission Revenue** | `/equity/revenue/commission` |
| **Intercompany Revenue** | `/equity/revenue/intercompany` |
| **Refunds & Allowances** | `/equity/revenue/refunds_allowances` |
| **Gain on Foreign Exchange (FX)** | `/equity/gain_fx` |
| **Payment Processing Expense** | `/expenses/processing/fees` |
| **Cost of Goods Sold** | `/expenses/cogs` |
| **Amortized Commission Expense**| `/expenses/commissions` |
| **Bad Debt Expense** | `/expenses/bad_debt` |
| **Loss on Foreign Exchange (FX)** | `/expenses/fx_loss` |
| **Intercompany Service Expense** | `/expenses/intercompany` |

---

## 4. Compiled Ledger Output Schema

A transaction compiled by the OLP engine must satisfy double-entry requirements: **total debits must exactly equal total credits.**

### Transaction Structure
```json
{
  "transaction_id": "tx_abc123",
  "source_event_id": "evt_100293",
  "idempotency_key": "idemp-9a8b7c6d-5e4f-3a2b",
  "date": "2026-07-16T08:00:00Z",
  "status": "posted",               // ["pending" | "posted"]
  "description": "Compiled OLP Transaction: Premium Subscription Annual Plan",
  "entries": [
    {
      "account": "/assets/liquid/cash",
      "type": "debit",
      "amount": 11620               // Net cash debited ($116.20)
    },
    {
      "account": "/expenses/processing/fees",
      "type": "debit",
      "amount": 380                 // Processing fee ($3.80)
    },
    {
      "account": "/liabilities/deferred/revenue",
      "type": "credit",
      "amount": 11000               // Base liability ($110.00)
    },
    {
      "account": "/liabilities/tax/payable/de",
      "type": "credit",
      "amount": 1000                // Dynamic Local Tax liability ($10.00)
    }
  ]
}
```

---

## 5. Compilation Rules & Double-Entry Math (In Cents)

The engine routes the event payload based on the `accounting_context` values and performs all arithmetic using integers.

### Rule A: Principal + Physical + Point-in-Time (Immediate Sale)
1. `Debit: [Asset Account]` (Gross Amount - Processing Fee) *[Skip fee if invoice]*
   * *Asset Account is `/assets/receivables/contract_assets` if billing_status is "unbilled", else `/assets/receivables/ar` if invoice, else `/assets/liquid/cash`*
2. `Debit: /expenses/processing/fees` (Processing Fee) *[Skip if invoice]*
3. `Credit: /equity/revenue/gross` (Gross Amount - Tax Amount)
4. `Credit: [Tax Account]` (Tax Amount)
   * *Tax Account is `/liabilities/tax/payable/<jurisdiction_id>` if `tax_jurisdiction` is provided, else `/liabilities/tax/payable`*
5. `Debit: /expenses/cogs` (COGS Estimate)
6. `Credit: /assets/inventory` (COGS Estimate)

### Rule B: Principal + Digital/SaaS + Over-Time (Initial Booking)
1. `Debit: [Asset Account]` (Gross Amount - Processing Fee)
2. `Debit: /expenses/processing/fees` (Processing Fee)
3. `Credit: /liabilities/deferred/revenue` (Gross Amount - Tax Amount)
4. `Credit: [Tax Account]` (Tax Amount)
* **Deferred Costs (ASC 340-40)**: If `capitalized_costs` is provided:
  5. `Debit: /assets/deferred_costs/commissions` (Capitalized Cost)
  6. `Credit: /liabilities/payables/commissions` (Capitalized Cost)
* **Amortization (per month)**: Monthly revenue = `(Gross Amount - Tax Amount) // term_months`. Monthly cost = `capitalized_costs // term_months`.
  * **Revenue Lines**:
    1. `Debit: /liabilities/deferred/revenue` (Monthly Revenue Cents)
    2. `Credit: /equity/revenue/subscription` (Monthly Revenue Cents)
  * **Cost Lines (ASC 340-40)**:
    3. `Debit: /expenses/commissions` (Monthly Cost Cents)
    4. `Credit: /assets/deferred_costs/commissions` (Monthly Cost Cents)

### Rule C: Agent + Physical + Point-in-Time (Immediate Sale)
* **Calculations**:
  * Base Price = Gross Amount - Tax Amount
  * Commission = `(Base Price * Platform Cut %) // 100`
  * Vendor Cut = Base Price - Commission
* **Entries**:
  1. `Debit: [Asset Account]` (Gross Amount - Processing Fee)
  2. `Debit: /expenses/processing/fees` (Processing Fee)
  3. `Credit: /liabilities/payables/vendor` (Vendor Cut)
  4. `Credit: /equity/revenue/commission` (Commission)
  5. `Credit: [Tax Account]` (Tax Amount)

### Rule D: Agent + Digital/SaaS + Over-Time (Initial Booking)
1. `Debit: [Asset Account]` (Gross Amount - Processing Fee)
2. `Debit: /expenses/processing/fees` (Processing Fee)
3. `Credit: /liabilities/deferred/payable_vendor` (Vendor Cut)
4. `Credit: /liabilities/deferred/commission` (Commission)
5. `Credit: [Tax Account]` (Tax Amount)
* **Amortization (per month)**:
  1. `Debit: /liabilities/deferred/payable_vendor` (Monthly Vendor Cents)
  2. `Credit: /liabilities/payables/vendor` (Monthly Vendor Cents)
  3. `Debit: /liabilities/deferred/commission` (Monthly Commission Cents)
  4. `Credit: /equity/revenue/commission` (Monthly Commission Cents)

---

## 6. Real-World Adjustments Specifications

### A. Accounts Receivable (AR) Invoicing Lifecycle
If `payment_method` is `"invoice"`, the Day 1 purchase event debits `Accounts Receivable` instead of `Cash`.
* **Initial booking (Day 1 invoice):**
  * `Debit: /assets/receivables/ar` (Gross Amount)
  * `Credit: /equity/revenue/gross` (Base Price)
  * `Credit: [Tax Account]` (Tax Amount)
* **Subsequent collection event (`"payment_settled"`):**
  * `Debit: /assets/liquid/cash` (Gross Amount - Processing Fee)
  * `Debit: /expenses/processing/fees` (Processing Fee)
  * `Credit: /assets/receivables/ar` (Gross Amount)

### B. Foreign Exchange (FX) Gains and Losses (ASC 830)
On a `"payment_settled"` event, if the locally settled `functional_amount` differs from the invoice's booked AR `amount`:
* Compute `fx_diff = functional_amount - amount`
* **If `fx_diff > 0` (Gain):**
  * `Debit: /assets/liquid/cash` (functional_amount - processing_fee)
  * `Debit: /expenses/processing/fees` (processing_fee)
  * `Credit: /assets/receivables/ar` (amount)
  * `Credit: /equity/gain_fx` (fx_diff)
* **If `fx_diff < 0` (Loss):**
  * `Debit: /assets/liquid/cash` (functional_amount - processing_fee)
  * `Debit: /expenses/processing/fees` (processing_fee)
  * `Debit: /expenses/fx_loss` (abs(fx_diff))
  * `Credit: /assets/receivables/ar` (amount)

### C. Contract Asset Conversion (ASC 606)
If revenue was initially recognized as an unbilled Contract Asset, compiling a `"contract_billed"` event shifts the receivable:
* `Debit: /assets/receivables/ar` (Gross Amount)
* `Credit: /assets/receivables/contract_assets` (Gross Amount)

### D. Bad Debt Write-offs
If a customer defaults on an outstanding invoice, compiling an `"invoice_written_off"` event cancels the receivable:
* `Debit: /expenses/bad_debt` (Outstanding Amount)
* `Credit: /assets/receivables/ar` (Outstanding Amount)

### E. Refunds and Inventory Returns
* **Event `"refund_issued"`**:
  * Records customer refund using a GAAP contra-revenue account rather than deleting transactions.
  * `Debit: /equity/revenue/refunds_allowances` (Base Price)
  * `Debit: [Tax Account]` (Tax Amount)
  * `Credit: /assets/liquid/cash` (Gross Amount) *[Or credit `/assets/receivables/ar` if payment method is invoice]*

---

## 7. Decoupled Multi-Pipeline Reconciliation (Amazon Scale)

For decoupled transactional setups where the sales pipeline runs separately from payment processor collections and treasury bank payouts:

### A. Business Order Placed (`"order_placed"`)
* `Debit: /assets/receivables/order_clearing` (Gross Amount)
* `Credit: /equity/revenue/gross` (Base Price)
* `Credit: [Tax Account]` (Tax Amount)

### B. Processor Charge Settled (`"charge_settled"`)
* `Debit: /assets/receivables/payment_clearing` (Gross Amount - Processing Fee)
* `Debit: /expenses/processing/fees` (Processing Fee)
* `Credit: /assets/receivables/order_clearing` (Gross Amount)

### C. Treasury Payout Cleared (`"payout_cleared"`)
* `Debit: /assets/liquid/cash` (Settled Net Amount)
* `Credit: /assets/receivables/payment_clearing` (Settled Net Amount)

---

## 8. Multinational Corporations (MNC) & Intercompany Transfers (ASC 810)

When billing occurs through one local subsidiary but infrastructure/fulfillment is performed by another parent entity, two distinct legal ledgers are compiled.

### A. Billing Entity (Subsidiary) Booking
Appends intercompany service lines to the subsidiary's ledger transactions:
* `Debit: /expenses/intercompany` (Intercompany Transfer Amount)
* `Credit: /liabilities/payables/intercompany_<partner_entity_id>` (Intercompany Transfer Amount)

### B. Fulfilling Entity (Partner/Parent) Booking
Generates a separate, balancing transaction for the partner's ledger:
* `Debit: /assets/receivables/intercompany_<subsidiary_entity_id>` (Intercompany Transfer Amount)
* `Credit: /equity/revenue/intercompany` (Intercompany Transfer Amount)
