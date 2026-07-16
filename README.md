# Open Ledger Protocol (OLP) Reference Implementation

This project contains the reference implementation of the **Open Ledger Protocol (OLP) Version 3.0**. 

OLP is an open, developer-centric financial accounting specification that abstracts standard double-entry bookkeeping rules out of application database layers. It acts like an "HTTP header" standard for sales events: by attaching key context headers (e.g., role, product type, recognition model), a checkout engine can post raw events and have them compiled into compliant, balanced journal entries dynamically.

## Key Features in Version 3.0

*   **Integer-Cents Arithmetic**: All money values are integers in minor currency units (cents, e.g. `$100.00` = `10000`) to avoid IEEE 754 float rounding errors.
*   **Standard Ledger Account Paths**: Account names map to hierarchical charts of accounts (e.g. `/assets/liquid/cash` or `/liabilities/deferred/revenue`) matching patterns used by enterprise engines like Twisp and Fragment.
*   **Fulfillment Lifecycles**: Supports separating cash payment events (`payment_received`) from delivery/fulfillment control transfer events (`fulfillment_completed`).
*   **Accounts Receivable Invoicing**: Supports B2B Net-30 invoice creation and wire cash settlement (`payment_settled`).
*   **GAAP Contra-Revenue & Returns**: Handles customer refunds (`refund_issued`) and physical warehouse inventory write-backs (`goods_returned`).
*   **Step 3 ASC 606 Proportional Discounts**: Transaction coupons are distributed proportionally across line items before recognition rules apply.
*   **Idempotency & Status**: Enforces `idempotency_key` payloads to prevent double-posting and includes transaction `status` fields (`posted`/`pending`).

---

## Project Structure

*   [SPECIFICATION.md](file:///Users/shivtatva/HomeProjects/open-ledger-protocol/SPECIFICATION.md): The draft OLP standards documentation defining payloads, headers, paths, and the compilation ruleset.
*   [engine.py](file:///Users/shivtatva/HomeProjects/open-ledger-protocol/engine.py): The Python reference implementation containing the compiler state machine.
*   [test_engine.py](file:///Users/shivtatva/HomeProjects/open-ledger-protocol/test_engine.py): Comprehensive unit tests covering the core scenarios and edge cases.
*   [demo.py](file:///Users/shivtatva/HomeProjects/open-ledger-protocol/demo.py): A runnable console application printing formatted, balanced ledger reports.
*   [COMPETITOR_COMPARISON.md](file:///Users/shivtatva/HomeProjects/open-ledger-protocol/COMPETITOR_COMPARISON.md): Analysis of OLP design patterns against Modern Treasury, Twisp, and Fragment.

---

## How to Run

To run the automated tests and verify the OLP engine:

```bash
python3 -m unittest test_engine.py
```

To run the console demo:

```bash
python3 demo.py
```
