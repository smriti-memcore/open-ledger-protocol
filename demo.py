from engine import OLPEngine, OLPEvent, AccountingContext, LineItem

def format_transaction(tx):
    print("=" * 80)
    print(f"Transaction ID:  {tx.transaction_id}")
    print(f"Source Event:    {tx.source_event_id}")
    print(f"Idempotency Key: {tx.idempotency_key}")
    print(f"Date:            {tx.date}")
    print(f"Status:          {tx.status.upper()}")
    print(f"Description:     {tx.description}")
    print("-" * 80)
    print(f"{'Standard Ledger Account Path':<45} | {'Type':<8} | {'Amount ($)':>12}")
    print("-" * 80)
    for entry in tx.entries:
        amt_dollars = entry.amount / 100.0
        amt_str = f"${amt_dollars:,.2f}"
        print(f"{entry.account:<45} | {entry.type.upper():<8} | {amt_str:>12}")
    print("=" * 80 + "\n")

def run_demo():
    print("RUNNING OPEN LEDGER PROTOCOL (OLP) DEMO - VERSION 1.0 (ADVANCED CPA PARITY)\n")
    
    # -------------------------------------------------------------------------
    # Scenario A: E-Commerce Retail Sale with VAT, Discount, and Stripe fees
    # -------------------------------------------------------------------------
    print("SCENARIO A: E-Commerce Retail Sale (VAT, discount code, and merchant card fees).")
    print("Customer buys a textbook (original $120.00 / 12000c) with a $20.00 (2000c) coupon.")
    print("Customer paid $108.00 (10800c) inclusive of $8.00 (800c) VAT. Stripe fee is $3.20 (320c).")
    event_a = OLPEvent(
        event_id="evt_ret_001",
        idempotency_key="idemp_retail_9a8b",
        timestamp="2026-07-16T12:00:00Z",
        amount=10800,
        currency="USD",
        description="Accounting 101 Book (Standard Order)",
        customer_id="cust_alice",
        tax_amount=800,
        processing_fee=320,
        discount_amount=2000,
        accounting_context=AccountingContext(
            role="principal",
            product_type="physical",
            recognition="point_in_time",
            payment_method="card"
        ),
        line_items=[
            LineItem(item_id="prod_textbook", price=12000, cogs_estimate=4500)
        ]
    )
    result_a = OLPEngine.compile_event(event_a)
    format_transaction(result_a.initial_transaction)

    # -------------------------------------------------------------------------
    # Scenario B: B2B Invoice FX Revaluation Lifecycle (ASC 830)
    # -------------------------------------------------------------------------
    print("SCENARIO B: B2B Invoice FX Revaluation Lifecycle (ASC 830).")
    print(">>> Day 1: Enterprise customer is invoiced $540.00 (54000c, inclusive of $40.00 VAT) net 30:")
    event_b_inv = OLPEvent(
        event_id="evt_inv_908",
        idempotency_key="idemp_invoice_5f4e",
        timestamp="2026-07-16T12:00:00Z",
        amount=54000,
        currency="USD",
        description="Enterprise Suite Annual License Invoice #908",
        customer_id="cust_bigcorp",
        tax_amount=4000,
        accounting_context=AccountingContext(
            role="principal",
            product_type="digital_download",
            recognition="point_in_time",
            payment_method="invoice"
        )
    )
    result_b_inv = OLPEngine.compile_event(event_b_inv)
    format_transaction(result_b_inv.initial_transaction)

    print(">>> Day 15: Wire settled in foreign currency. Conversion rate yields $520.00 (52000c).")
    print("This results in a $20.00 (2000c) FX loss. Wire fee is $15.00 (1500c).")
    event_b_pay = OLPEvent(
        event_id="evt_settle_908",
        event_type="payment_settled",
        idempotency_key="idemp_settle_3d2c",
        timestamp="2026-07-31T09:00:00Z",
        amount=54000,
        currency="USD",
        description="Wire Payment Settled with FX Revaluation",
        customer_id="cust_bigcorp",
        processing_fee=1500,
        functional_amount=52000,
        accounting_context=AccountingContext(
            role="principal",
            product_type="digital_download",
            recognition="point_in_time",
            payment_method="invoice"
        )
    )
    result_b_pay = OLPEngine.compile_event(event_b_pay)
    format_transaction(result_b_pay.initial_transaction)

    # -------------------------------------------------------------------------
    # Scenario C: SaaS Subscription with Amortized Commission Costs (ASC 340-40)
    # -------------------------------------------------------------------------
    print("SCENARIO C: SaaS subscription over 3 months with Amortized Commissions (ASC 340-40).")
    print("Customer paid $300.00 (30000c). Salesperson paid $12.00 (1200c) commission.")
    event_c = OLPEvent(
        event_id="evt_saas_costs",
        idempotency_key="idemp_saas_costs",
        timestamp="2026-07-16T12:00:00Z",
        amount=30000,
        currency="USD",
        description="Premium Dev Plan (Quarterly Sub)",
        customer_id="cust_dev_user",
        capitalized_costs=1200,
        accounting_context=AccountingContext(
            role="principal",
            product_type="digital_saas",
            recognition="over_time",
            term_months=3,
            payment_method="card"
        )
    )
    result_c = OLPEngine.compile_event(event_c)
    print(">>> Initial Cash, Deferred Revenue & Commission Cost bookings:")
    format_transaction(result_c.initial_transaction)
    print(">>> Monthly Amortization schedules (matching revenue and commission expense amortization):")
    for month_tx in result_c.amortization_schedule:
        format_transaction(month_tx)

    # -------------------------------------------------------------------------
    # Scenario D: Contract Asset (Unbilled AR) Billing Lifecycle (ASC 606)
    # -------------------------------------------------------------------------
    print("SCENARIO D: Contract Asset (Unbilled AR) Billing Lifecycle (ASC 606).")
    print(">>> Day 1: Recognize unbilled milestone revenue of $200.00 (20000c):")
    event_d_unb = OLPEvent(
        event_id="evt_unb_milestone",
        timestamp="2026-07-16T12:00:00Z",
        amount=20000,
        currency="USD",
        description="Unbilled Milestones completed",
        customer_id="cust_client",
        idempotency_key="idemp_unb_mile",
        accounting_context=AccountingContext(
            role="principal",
            product_type="digital_download",
            recognition="point_in_time",
            payment_method="invoice",
            billing_status="unbilled"
        )
    )
    result_d_unb = OLPEngine.compile_event(event_d_unb)
    format_transaction(result_d_unb.initial_transaction)

    print(">>> Day 15: Bill the milestones. Converts $200.00 Contract Asset into billed AR:")
    event_d_bill = OLPEvent(
        event_id="evt_bill_milestone",
        event_type="contract_billed",
        timestamp="2026-07-30T12:00:00Z",
        amount=20000,
        currency="USD",
        description="Convert milestones to Accounts Receivable",
        customer_id="cust_client",
        idempotency_key="idemp_bill_mile",
        accounting_context=AccountingContext(
            role="principal",
            product_type="digital_download",
            recognition="point_in_time"
        )
    )
    result_d_bill = OLPEngine.compile_event(event_d_bill)
    format_transaction(result_d_bill.initial_transaction)

    # -------------------------------------------------------------------------
    # Scenario E: Invoice default & Bad Debt write-off
    # -------------------------------------------------------------------------
    print("SCENARIO E: Invoice default & Bad Debt write-off.")
    print("An outstanding customer invoice of $150.00 (15000c) is written off as uncollectible:")
    event_e_wo = OLPEvent(
        event_id="evt_write_off_inv",
        event_type="invoice_written_off",
        timestamp="2026-07-25T12:00:00Z",
        amount=15000,
        currency="USD",
        description="Write off defaulted client invoice",
        customer_id="cust_bad_user",
        idempotency_key="idemp_wo_inv",
        accounting_context=AccountingContext(
            role="principal",
            product_type="digital_download",
            recognition="point_in_time"
        )
    )
    result_e_wo = OLPEngine.compile_event(event_e_wo)
    format_transaction(result_e_wo.initial_transaction)

    # -------------------------------------------------------------------------
    # Scenario F: Decoupled Multi-Pipeline Reconciliation (Amazon Scale)
    # -------------------------------------------------------------------------
    print("SCENARIO F: Decoupled Multi-Pipeline Reconciliation (Amazon Scale).")
    print(">>> Stage 1: Checkout places order for $108.00 (10800c inclusive of $8.00 VAT) - Business side:")
    event_f_order = OLPEvent(
        event_id="order_556677",
        event_type="order_placed",
        timestamp="2026-07-16T12:00:00Z",
        amount=10800,
        currency="USD",
        description="Business Side order checkout",
        customer_id="cust_sam",
        tax_amount=800,
        idempotency_key="idemp_order_556",
        accounting_context=AccountingContext(
            role="principal",
            product_type="physical",
            recognition="point_in_time",
            payment_method="card"
        )
    )
    result_f_order = OLPEngine.compile_event(event_f_order)
    format_transaction(result_f_order.initial_transaction)

    print(">>> Stage 2: Card gateway processes charge, logging $3.20 (320c) fee - Payments side:")
    event_f_settle = OLPEvent(
        event_id="settle_556677",
        event_type="charge_settled",
        timestamp="2026-07-16T12:05:00Z",
        amount=10800,
        processing_fee=320,
        currency="USD",
        description="Card processor captures checkout payment",
        customer_id="cust_sam",
        idempotency_key="idemp_settle_556",
        accounting_context=AccountingContext(
            role="principal",
            product_type="physical",
            recognition="point_in_time"
        )
    )
    result_f_settle = OLPEngine.compile_event(event_f_settle)
    format_transaction(result_f_settle.initial_transaction)

    print(">>> Stage 3: Operating bank payouts clear. Stripe deposits net cash of $104.80 (10480c):")
    event_f_payout = OLPEvent(
        event_id="payout_556677",
        event_type="payout_cleared",
        timestamp="2026-07-18T06:00:00Z",
        amount=10480,
        currency="USD",
        description="Bank payout sweep cleared",
        customer_id="cust_sam",
        idempotency_key="idemp_payout_556",
        accounting_context=AccountingContext(
            role="principal",
            product_type="physical",
            recognition="point_in_time"
        )
    )
    result_f_payout = OLPEngine.compile_event(event_f_payout)
    format_transaction(result_f_payout.initial_transaction)

if __name__ == "__main__":
    run_demo()
