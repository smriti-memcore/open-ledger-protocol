# Open Ledger Protocol (OLP) Reference Implementation

This project contains a working reference implementation of the **Open Ledger Protocol (OLP)**. 

OLP is a developer-centric financial accounting specification that abstracts standard double-entry bookkeeping rules out of business application database layers. It acts like an "HTTP header" standard for sales events: by attaching key context headers (e.g., role, product type, recognition model), a checkout engine can post raw events and have them compiled into compliant, balanced journal entries dynamically.

## Project Structure

*   [SPECIFICATION.md](file:///Users/shivtatva/HomeProjects/open-ledger-protocol/SPECIFICATION.md): The draft OLP standards documentation defining payloads, headers, and the compilation ruleset.
*   [engine.py](file:///Users/shivtatva/HomeProjects/open-ledger-protocol/engine.py): The Python reference implementation containing the compiler state machine.
*   [test_engine.py](file:///Users/shivtatva/HomeProjects/open-ledger-protocol/test_engine.py): Comprehensive unit tests covering the four major matrix scenarios:
    1.  **Rule A (Principal + Physical + Point-in-Time):** Standard physical retail/e-commerce.
    2.  **Rule B (Principal + Digital/SaaS + Over-Time):** Standard SaaS recurring revenue.
    3.  **Rule C (Agent + Physical + Point-in-Time):** Marketplace selling physical goods.
    4.  **Rule D (Agent + Digital/SaaS + Over-Time):** Subscription platforms / App stores.

---

## How to Run

To run the automated tests and verify the OLP engine:

```bash
python3 -m unittest test_engine.py
```

### Extending the Protocol

To add custom parameters (such as localization headers for VAT/sales tax logic or currency hedging flags), extend the `AccountingContext` class in `engine.py` and implement the corresponding state-routing logic.
