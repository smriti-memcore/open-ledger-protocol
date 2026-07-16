# Open Ledger Protocol (OLP) Specification
**Version 1.0.0-draft**

The **Open Ledger Protocol (OLP)** defines a standardized, metadata-driven system for financial accounting integrations. By decoupling business event creation from ledger compilation, OLP allows commerce/checkout platforms to send generic transaction events, which are dynamically mapped to double-entry ledger entries.

---

## 1. Accounting Context Headers

Every OLP-compliant payload contains a global `accounting_context` block. Localized `accounting_context` overrides can also be specified at the **Line-Item** level to support multi-element bundles.

| Header Field | Type | Allowed Values | Description |
| :--- | :--- | :--- | :--- |
| `entity_id` | String | e.g. `"acme_us"` | Identifies the primary billing legal entity (subsidiary) responsible for the sale. |
| `segment_id` | String | e.g. `"aws"`, `"twitch"` | Operating segment / line of business (LOB) classification for divisional reports (ASC 280). |
| `is_intercompany`| Boolean | `true`, `false` | Tag indicating if the transaction is internal (intercompany) for downstream consolidation eliminations (ASC 810). |
| `role` | String | `"principal"`, `"agent"` | Determines if the business sells as a principal (gross revenue) or as an agent (net commission). |
| `product_type` | String | `"physical"`, `"digital_saas"`, `"digital_download"` | Determines the nature of the product and cost implications. |
| `recognition` | String | `"point_in_time"`, `"over_time"` | Dictates whether revenue is recognized immediately or ratably over a term. |
| `term_months` | Integer | >= 1 | Required if `recognition` is `"over_time"`. The amortization period in months. |
| `payment_method`| String | `"card"`, `"invoice"` | Determines debit side asset routing (Cash/Card Clearing vs. Accounts Receivable). |
| `billing_status`| String | `"billed"`, `"unbilled"` | Determines asset routing for unbilled work (Accounts Receivable vs. Contract Assets). |
| `coa_overrides` | Dictionary | `{ "Default Account": "Custom Path" }` | Dynamic dictionary to override default chart of accounts routing paths on a per-brand basis. |

---

## 2. Event Payload Schema

A standard OLP event payload contains transactional details, metadata routing headers, a required idempotency key, and monetary adjustments. 

> [!IMPORTANT]
> **Minor Currency Units (Integers)**: All money values in OLP must be represented as integers in their minor currency units (e.g., $120.00 is represented as `12000` cents). This eliminates floating-point rounding errors.

```json
{
  "event_id": "evt_100293",
  "event_type": "payment_received", // ["payment_received" | "fulfillment_completed" | "immediate_sale" | "payment_settled" | "refund_issued" | "goods_returned" | "contract_billed" | "invoice_written_off" | "order_placed" | "charge_settled" | "payout_cleared" | "gift_card_purchased" | "gift_card_redeemed" | "gift_card_breakage_recognized"]
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
  "expected_return_rate_basis_points": 300, // Expected returns reserve in basis points (e.g. 300 bps = 3% return rate) (ASC 606)
  "intercompany_entity_id": "acme_us", // Partner entity fulfilling order (ASC 810)
  "intercompany_transfer_amount": 8500, // Transfer pricing fee to route to partner books ($85.00 = 8500)
  "accounting_context": {
    "entity_id": "acme_de",
    "segment_id": "audible",
    "is_intercompany": false,
    "role": "principal",
    "product_type": "digital_saas",
    "recognition": "over_time",
    "term_months": 12,
    "payment_method": "card",
    "billing_status": "billed",
    "coa_overrides": {
      "Subscription Revenue": "/equity/revenue/audio_subscriptions"
    }
  },
  "line_items": [
    {
      "item_id": "prod_premium_annual",
      "price": 12000,
      "cogs_estimate": 0,
      "accounting_context": { // Optional line-item override (ASC 606 Bundle)
        "role": "principal",
        "product_type": "digital_saas",
        "recognition": "over_time",
        "term_months": 12
      }
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
| **Right to Recover Returned Goods**| `/assets/receivables/right_to_recover` |
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
| **Refund Reserve Liability** | `/liabilities/refund_reserve` |
| **Gift Card Liability** | `/liabilities/gift_card` |
| **Gross Revenue** | `/equity/revenue/gross` |
| **Subscription Revenue** | `/equity/revenue/subscription` |
| **Commission Revenue** | `/equity/revenue/commission` |
| **Intercompany Revenue** | `/equity/revenue/intercompany` |
| **Gift Card Breakage Revenue** | `/equity/revenue/breakage` |
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
  "consolidation_type": "standard", // ["standard" | "elimination"] (ASC 810)
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
3. **Revenue Splits**:
   * If `expected_return_rate_basis_points > 0`:
     * Refund Reserve = `((Gross Amount - Tax Amount) * expected_return_rate_basis_points) // 10000`
     * Recognized Revenue = `(Gross Amount - Tax Amount) - Refund Reserve`
     * `Credit: [Gross Revenue Account]` (Recognized Revenue)
     * `Credit: /liabilities/refund_reserve` (Refund Reserve)
   * Else:
     * `Credit: [Gross Revenue Account]` (Gross Amount - Tax Amount)
4. `Credit: [Tax Account]` (Tax Amount)
5. **COGS Splits**:
   * If `expected_return_rate_basis_points > 0`:
     * Recoverable Cost = `(COGS Estimate * expected_return_rate_basis_points) // 10000`
     * Net COGS = `COGS Estimate - Recoverable Cost`
     * `Debit: /expenses/cogs` (Net COGS)
     * `Debit: /assets/receivables/right_to_recover` (Recoverable Cost)
   * Else:
     * `Debit: /expenses/cogs` (COGS Estimate)
6. `Credit: /assets/inventory` (COGS Estimate)

### Rule B: Principal + Digital/SaaS + Over-Time (Initial Booking)
1. `Debit: [Asset Account]` (Gross Amount - Processing Fee)
2. `Debit: /expenses/processing/fees` (Processing Fee)
3. `Credit: [Deferred Revenue Account]` (Gross Amount - Tax Amount)
4. `Credit: [Tax Account]` (Tax Amount)
* **Deferred Costs (ASC 340-40)**: If `capitalized_costs` is provided:
  5. `Debit: /assets/deferred_costs/commissions` (Capitalized Cost)
  6. `Credit: /liabilities/payables/commissions` (Capitalized Cost)
* **Amortization (per month)**: Monthly revenue = `(Gross Amount - Tax Amount) // term_months`. Monthly cost = `capitalized_costs // term_months`.
  * **Revenue Lines**:
    1. `Debit: [Deferred Revenue Account]` (Monthly Revenue Cents)
    2. `Credit: [Subscription Revenue Account]` (Monthly Revenue Cents)
  * **Cost Lines (ASC 340-40)**:
    3. `Debit: /expenses/commissions` (Monthly Cost Cents)
    4. `Credit: /assets/deferred_costs/commissions` (Monthly Cost Cents)

---

## 6. Real-World Adjustments Specifications

### A. Gift Card Lifecycles
* **Event `"gift_card_purchased"`**:
  * `Debit: /assets/liquid/cash` (Gross Amount - Processing Fee)
  * `Debit: /expenses/processing/fees` (Processing Fee)
  * `Credit: /liabilities/gift_card` (Gross Amount)
* **Event `"gift_card_redeemed"`**:
  * `Debit: /liabilities/gift_card` (Redeemed Amount)
  * `Credit: /equity/revenue/gross` (Redeemed Amount)
* **Event `"gift_card_breakage_recognized"`**:
  * `Debit: /liabilities/gift_card` (Breakage Amount)
  * `Credit: /equity/revenue/breakage` (Breakage Amount)
