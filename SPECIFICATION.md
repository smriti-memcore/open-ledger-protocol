# Open Ledger Protocol (OLP) Specification
**Version 2.0.0-draft**

The **Open Ledger Protocol (OLP)** defines a standardized, metadata-driven system for financial accounting integrations. By decoupling business event creation from ledger compilation, OLP allows commerce/checkout platforms to send generic transaction events, which are dynamically mapped to double-entry ledger entries.

---

## 1. Accounting Context Headers

Every OLP-compliant payload contains an `accounting_context` block. This block acts as the routing header for the double-entry compiler.

| Header Field | Type | Allowed Values | Description |
| :--- | :--- | :--- | :--- |
| `role` | String | `"principal"`, `"agent"` | Determines if the business sells as a principal (gross revenue) or as an agent (net commission). |
| `product_type` | String | `"physical"`, `"digital_saas"`, `"digital_download"` | Determines the nature of the product and cost implications. |
| `recognition` | String | `"point_in_time"`, `"over_time"` | Dictates whether revenue is recognized immediately or ratably over a term. |
| `term_months` | Integer | >= 1 | Required if `recognition` is `"over_time"`. The amortization period in months. |
| `payment_method`| String | `"card"`, `"invoice"` | Determines debit side asset routing (Cash/Card Clearing vs. Accounts Receivable). |

---

## 2. Event Payload Schema

A standard OLP event payload contains transactional details, the metadata routing headers, and optional financial adjustments (discounts, taxes, processing fees).

```json
{
  "event_id": "evt_100293",
  "event_type": "payment_received", // ["payment_received" | "fulfillment_completed" | "immediate_sale" | "payment_settled" | "refund_issued" | "goods_returned"]
  "timestamp": "2026-07-16T08:00:00Z",
  "amount": 120.00,                 // Gross amount collected from customer (inclusive of tax)
  "currency": "USD",
  "description": "Premium Subscription Annual Plan",
  "customer_id": "cust_8829",
  "tax_amount": 10.00,              // Taxes included in the amount (Sales Tax / VAT)
  "processing_fee": 3.80,           // Merchant gateway transaction charges
  "discount_amount": 20.00,         // Transaction-level discount to distribute
  "accounting_context": {
    "role": "principal",
    "product_type": "digital_saas",
    "recognition": "over_time",
    "term_months": 12,
    "payment_method": "card"
  },
  "line_items": [
    {
      "item_id": "prod_premium_annual",
      "price": 120.00,
      "cogs_estimate": 0.00
    }
  ]
}
```

---

## 3. Compiled Ledger Output Schema

A transaction compiled by the OLP engine must satisfy double-entry requirements: **total debits must exactly equal total credits.**

### Transaction Structure
```json
{
  "transaction_id": "tx_abc123",
  "source_event_id": "evt_100293",
  "date": "2026-07-16T08:00:00Z",
  "description": "Compiled OLP Transaction: Premium Subscription Annual Plan",
  "entries": [
    {
      "account": "Cash",
      "type": "debit",
      "amount": 116.20
    },
    {
      "account": "Payment Processing Expense",
      "type": "debit",
      "amount": 3.80
    },
    {
      "account": "Deferred Revenue",
      "type": "credit",
      "amount": 110.00
    },
    {
      "account": "Sales Tax Payable",
      "type": "credit",
      "amount": 10.00
    }
  ]
}
```

---

## 4. Compilation Matrix & Core Rules

The OLP compilation engine routes the event payload based on the `accounting_context` values.

### Rule A: Principal + Physical + Point-in-Time
* **Accounting Treatment:** Recognize gross revenue immediately (adjusted for tax). Adjust inventory/COGS immediately.
* **Entries (Immediate Sale):**
  1. `Debit: Cash` (Gross Amount - Processing Fee)
  2. `Debit: Payment Processing Expense` (Processing Fee)
  3. `Credit: Gross Revenue` (Gross Amount - Tax Amount)
  4. `Credit: Sales Tax Payable` (Tax Amount)
  5. `Debit: Cost of Goods Sold` (COGS Estimate)
  6. `Credit: Inventory` (COGS Estimate)

### Rule B: Principal + Digital/SaaS + Over-Time
* **Accounting Treatment:** Recognize initial cash and deferred liability (adjusted for tax). Amortize revenue ratably.
* **Entries (Initial booking):**
  1. `Debit: Cash` (Gross Amount - Processing Fee)
  2. `Debit: Payment Processing Expense` (Processing Fee)
  3. `Credit: Deferred Revenue` (Gross Amount - Tax Amount)
  4. `Credit: Sales Tax Payable` (Tax Amount)
* **Entries (Amortization schedule):**
  * Generate $N$ monthly schedules where monthly amount = $\frac{\text{Gross Amount} - \text{Tax Amount}}{\text{term\_months}}$:
    1. `Debit: Deferred Revenue` (Monthly Amount)
    2. `Credit: Subscription Revenue` (Monthly Amount)

### Rule C: Agent + Physical + Point-in-Time
* **Accounting Treatment:** Recognize net commission immediately (adjusted for tax), and hold vendor payout.
* **Calculations:**
  * Base Price = Gross Amount - Tax Amount
  * Commission = Base Price * Platform Cut %
  * Vendor Cut = Base Price - Commission
* **Entries (Immediate Sale):**
  1. `Debit: Cash` (Gross Amount - Processing Fee)
  2. `Debit: Payment Processing Expense` (Processing Fee)
  3. `Credit: Accounts Payable (Vendor)` (Vendor Cut)
  4. `Credit: Commission Revenue` (Commission)
  5. `Credit: Sales Tax Payable` (Tax Amount)

### Rule D: Agent + Digital/SaaS + Over-Time
* **Accounting Treatment:** Recognize cash, track deferred vendor payable and deferred commission, and amortize over time.
* **Calculations:**
  * Base Price = Gross Amount - Tax Amount
  * Commission = Base Price * Platform Cut %
  * Vendor Cut = Base Price - Commission
* **Entries (Initial booking):**
  1. `Debit: Cash` (Gross Amount - Processing Fee)
  2. `Debit: Payment Processing Expense` (Processing Fee)
  3. `Credit: Deferred Payable (Vendor)` (Vendor Cut)
  4. `Credit: Deferred Commission Revenue` (Commission)
  5. `Credit: Sales Tax Payable` (Tax Amount)
* **Entries (Amortization schedule):**
  * Generate $N$ monthly schedules:
    1. `Debit: Deferred Payable (Vendor)` (Monthly Vendor Cut)
    2. `Credit: Accounts Payable (Vendor)` (Monthly Vendor Cut)
    3. `Debit: Deferred Commission Revenue` (Monthly Platform Cut)
    4. `Credit: Commission Revenue` (Monthly Platform Cut)

---

## 5. Fulfillment Lifecycles & Delivery

For point-in-time transactions where payment and delivery occur at different times:

### A. Phase 1: `payment_received` (No transfer of control yet)
* **Entries:**
  1. `Debit: Cash` (Gross Amount - Processing Fee)
  2. `Debit: Payment Processing Expense` (Processing Fee)
  3. `Credit: Deferred Revenue` (Gross Amount - Tax Amount)
  4. `Credit: Sales Tax Payable` (Tax Amount)

### B. Phase 2: `fulfillment_completed` (Control transfers to customer)
* **Entries:**
  1. `Debit: Deferred Revenue` (Gross Amount - Tax Amount)
  2. `Credit: Gross Revenue` (Gross Amount - Tax Amount)
  3. `Debit: Cost of Goods Sold` (COGS Estimate)
  4. `Credit: Inventory` (COGS Estimate)

---

## 6. Real-World Adjustments Specifications

### A. Accounts Receivable (AR) Invoicing Lifecycle
If `payment_method` is `"invoice"`, the Day 1 purchase event debits `Accounts Receivable` instead of `Cash` and bypasses the `processing_fee` (which is typically zero or charged later).
* **Initial booking (Day 1 invoice):**
  * `Debit: Accounts Receivable` (Gross Amount)
  * `Credit: Deferred/Gross Revenue` (Base Price)
  * `Credit: Sales Tax Payable` (Tax Amount)
* **Subsequent collection event (`"payment_settled"`):**
  * `Debit: Cash` (Gross Amount - Processing Fee)
  * `Debit: Payment Processing Expense` (Processing Fee)
  * `Credit: Accounts Receivable` (Gross Amount)

### B. Refunds and Inventory Returns
* **Event `"refund_issued"`**:
  * Records customer refund using a GAAP contra-revenue account rather than deleting transactions.
  * `Debit: Refunds & Allowances` (Base Price)
  * `Debit: Sales Tax Payable` (Tax Amount)
  * `Credit: Cash` (or `Accounts Receivable` if outstanding)
* **Event `"goods_returned"`**:
  * Reverses cost of goods sold and restores physical inventory to stock.
  * `Debit: Inventory` (Original COGS)
  * `Credit: Cost of Goods Sold` (Original COGS)

### C. Proportional Discount Allocations (ASC 606 Step 3)
If a transaction-level `discount_amount` is provided, the compiler must distribute it proportionally across all line items based on their standalone pricing weights before applying recognition rules.
* **Formula**:
  $$\text{Net Price}_i = \text{Price}_i - \left( \text{Discount} \times \frac{\text{Price}_i}{\sum \text{Price}} \right)$$
