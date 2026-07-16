# Competitor & Schema Comparison: OLP vs. Modern Treasury, Twisp, and Fragment

To ensure the **Open Ledger Protocol (OLP)** stands up to production-grade enterprise ledger standards, we analyzed the API schemas and architectural designs of the leading commercial financial infrastructure engines: **Modern Treasury (Ledgers API)**, **Twisp**, and **Fragment.dev**.

---

## 1. Technical Comparison Matrix

| Feature | Modern Treasury | Twisp / Fragment | OLP (Current v2) |
| :--- | :--- | :--- | :--- |
| **Data Representation** | Cents (Integers, e.g. `5000` = $50) | Decimals / Arbitrary Strings | Float (with `round(x, 2)`) |
| **Transaction States** | `pending` / `posted` | Lifecycle status fields | Stateful event lifecycles (Event Types) |
| **Account Hierarchy** | Flat Accounts with Categories | Tree-structured Account Paths | Flat Account strings |
| **Integrations** | Bank accounts & clearing | GraphQL endpoints | Protocol compilation (Engine maps metadata) |
| **Immutability Enforcement**| App-level checks on posted items | Append-only event-sourced DB | Stateless compiler (Relies on database layer) |
| **Concurrency Control** | Optimistic Locking | Lock-free balance layers | Stateless (Left to host system) |

---

## 2. Gaps and How to Address Them

### Gap A: Float vs. Integer Representation (Rounding Vulnerability)
* **The Issue:** OLP currently uses floating-point numbers (`float`) in JSON and compiles entries with standard floats (`120.00`). Floating-point arithmetic under IEEE 754 is prone to rounding errors (e.g. `0.1 + 0.2 = 0.30000000000000004`). In production finance, this is a blocker.
* **Industry Standard:** Modern Treasury and Twisp use **Integers representing the smallest currency unit** (cents for USD, EUR). A $100.00 sale is represented as `10000`.
* **OLP Recommendation:** Define in the schema that all numerical fields (`amount`, `tax_amount`, `processing_fee`, `price`) should be integer values representing the minor currency unit.

### Gap B: Account Hierarchy Paths (Chart of Accounts)
* **The Issue:** OLP mapped accounts as simple flat strings (e.g., `"Cash"`, `"Gross Revenue"`). For enterprise audits, accounts must map to a standardized hierarchical chart of accounts (e.g. `/assets/cash/stripe` vs. `/liabilities/deferred_revenue/saas`).
* **Industry Standard:** Fragment and Twisp support hierarchical tree structures for ledger accounts to aggregate roll-up balances.
* **OLP Recommendation:** Define standard accounts in the specification as structured path strings rather than flat words.

### Gap C: Idempotency & Deduplication Keys
* **The Issue:** If a webhook fails and the checkout system retries sending an event, OLP could compile a duplicate transaction. 
* **Industry Standard:** Modern Treasury enforces strict idempotency at the API boundary, rejecting requests with duplicate `idempotency_key` values.
* **OLP Recommendation:** Require an `idempotency_key` header inside the event payload metadata.

### Gap D: Balance Layering (Pending vs. Posted Balances)
* **The Issue:** B2B invoices or pending card charges are in-flight transactions. We currently map them as separate events, but don't define the transition state (e.g. how a transaction goes from `pending` to `posted` to update "Available vs. Ledger" balances).
* **Industry Standard:** Ledgers separate balances into `posted` (cleared) and `pending` (authorized but not cleared).
* **OLP Recommendation:** Include a `transaction_status` field (`pending` | `posted`) in the output schema.
