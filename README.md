# Open Ledger Protocol (OLP) Reference Implementation

This repository contains the official reference implementation of the **Open Ledger Protocol (OLP) Version 1.0.0-draft**.

OLP is an open, developer-centric financial accounting specification that abstracts standard double-entry bookkeeping rules out of application database layers. It acts like an "HTTP header" standard for commerce events: by attaching context headers (such as role, product type, recognition model, tax jurisdiction, and LOB segment), raw billing/order events are compiled into GAAP/IFRS-compliant, balanced journal entries dynamically.

---

## Key Features in Version 1.0

*   **GAAP/ASC Parity Rules**:
    *   **ASC 606 (Revenue Recognition)**: Supports Point-in-Time, Over-Time ratable revenue amortization schedules, Contract Assets (Unbilled AR), Expected Returns Reserves splits, and Line-Item Bundle Allocations (Step 4).
    *   **ASC 340-40 (Capitalized Costs)**: capitalizes and amortizes customer acquisition costs (e.g. salesperson commissions) alongside deferred revenue.
    *   **ASC 830 (Foreign Exchange)**: Realized FX gains/losses calculations at wire payment cash settlement.
    *   **ASC 810 (Intercompany Consolidations)**: Auto-compiles subsidiary and parent fulfiller books, tagging internal trades with `consolidation_type = "elimination"` to bypass parent consolidated earnings.
    *   **ASC 280 (Segment Reporting)**: Segregates logs by brand line of business (`segment_id`) for divisional balance sheets.
*   **Integer-Cents Arithmetic**: All monetary fields are integer values in minor currency units (cents, e.g. `$100.00` = `10000`) to completely eliminate IEEE 754 floating-point rounding errors.
*   **Standard Ledger Account Paths**: Account names map to hierarchical chart of accounts paths (e.g. `/assets/liquid/cash` or `/liabilities/deferred/revenue`) matching patterns in Twisp and Fragment.
*   **Decoupled Multi-Pipeline Reconciliation**: Decouples business-side checkout events (`order_placed`) from payment processing (`charge_settled`) and sweeps (`payout_cleared`) using order/payment clearing sub-ledgers.
*   **Gift Card Lifecycles**: Standardized compilation rules for gift card purchases (liabilities), redemptions (revenue), and breakage sweeps.
*   **Post-Transaction Adjustments**: Supports variable consideration adjustments (`revenue_adjustment_posted`), direct invoice voiding (`invoice_voided` reversing AR/revenue without bad debt expense), and accrual reversals (`accrual_reversed`).
*   **Idempotency Protection**: Enforces `idempotency_key` headers to guarantee transactional safety and prevent double-posting.

---

## Project Structure

*   [SPECIFICATION.md](file:///Users/shivtatva/HomeProjects/open-ledger-protocol/SPECIFICATION.md): The OLP protocol standards document defining payloads, context metadata, paths, and double-entry compilation math.
*   [engine.py](file:///Users/shivtatva/HomeProjects/open-ledger-protocol/engine.py): The core Python reference compiler executing the accounting state machines.
*   [test_engine.py](file:///Users/shivtatva/HomeProjects/open-ledger-protocol/test_engine.py): Comprehensive test suite covering 22 complex GAAP scenario unit tests.
*   [demo.py](file:///Users/shivtatva/HomeProjects/open-ledger-protocol/demo.py): A runnable console script demonstrating 14 detailed end-to-end scenarios (Scenarios A through N).
*   [COMPETITOR_COMPARISON.md](file:///Users/shivtatva/HomeProjects/open-ledger-protocol/COMPETITOR_COMPARISON.md): Analysis comparing OLP design patterns against Modern Treasury, Twisp, and Fragment.

---

## How to Run

To execute the automated unit test suite:
```bash
python3 -m unittest test_engine.py
```

To run the end-to-end scenario demonstration app:
```bash
python3 demo.py
```
