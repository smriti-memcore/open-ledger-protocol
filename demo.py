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
        # Convert minor unit cents back to dollars for the readable display
        amt_dollars = entry.amount / 100.0
        amt_str = f"${amt_dollars:,.2f}"
        print(f"{entry.account:<45} | {entry.type.upper():<8} | {amt_str:>12}")
    print("=" * 80 + "\n")

def run_demo():
    print("RUNNING OPEN LEDGER PROTOCOL (OLP) DEMO - VERSION 3.0 (ENTERPRISE PATHS & CENTS)\n")
    
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
    # Scenario B: B2B Invoice Lifecycle (Accounts Receivable aging)
    # -------------------------------------------------------------------------
    print("SCENARIO B: B2B Invoice Lifecycle (Accounts Receivable flow).")
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

    print(">>> Day 15: BigCorp settles invoice via Wire. Wire transfer fee is $15.00 (1500c):")
    event_b_pay = OLPEvent(
        event_id="evt_settle_908",
        event_type="payment_settled",
        idempotency_key="idemp_settle_3d2c",
        timestamp="2026-07-31T09:00:00Z",
        amount=54000,
        currency="USD",
        description="Wire Payment Settled for Invoice #908",
        customer_id="cust_bigcorp",
        processing_fee=1500,
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
    # Scenario C: SaaS Subscription (Over-Time) with Tax and Card Fee splits
    # -------------------------------------------------------------------------
    print("SCENARIO C: SaaS subscription recognized over 3 months with Tax/Fee splits.")
    print("Customer paid $105.00 / 10500c ($100 base + $5 sales tax). Card fee was $3.00 / 300c.")
    event_c = OLPEvent(
        event_id="evt_saas_700",
        idempotency_key="idemp_saas_4d9f",
        timestamp="2026-07-16T12:00:00Z",
        amount=10500,
        currency="USD",
        description="Developer Plan (Quarterly Sub)",
        customer_id="cust_dev_user",
        tax_amount=500,
        processing_fee=300,
        accounting_context=AccountingContext(
            role="principal",
            product_type="digital_saas",
            recognition="over_time",
            term_months=3,
            payment_method="card"
        )
    )
    result_c = OLPEngine.compile_event(event_c)
    print(">>> Initial Cash & Deferred Liability splits:")
    format_transaction(result_c.initial_transaction)
    print(">>> Monthly Amortization schedules (base revenue only):")
    for month_tx in result_c.amortization_schedule:
        format_transaction(month_tx)

    # -------------------------------------------------------------------------
    # Scenario D: Returns and Refunds Processing
    # -------------------------------------------------------------------------
    print("SCENARIO D: Returns and Refunds (Contra-Revenue & Inventory write-back).")
    print(">>> Step 1: Customer returns textbook, refunding $108.00 / 10800c ($100.00 base + $8.00 VAT):")
    event_d_ref = OLPEvent(
        event_id="evt_ref_301",
        idempotency_key="idemp_refund_8e7f",
        event_type="refund_issued",
        timestamp="2026-07-20T14:00:00Z",
        amount=10800,
        currency="USD",
        description="Refund for Textbook Order",
        customer_id="cust_alice",
        tax_amount=800,
        accounting_context=AccountingContext(
            role="principal",
            product_type="physical",
            recognition="point_in_time",
            payment_method="card"
        )
    )
    result_d_ref = OLPEngine.compile_event(event_d_ref)
    format_transaction(result_d_ref.initial_transaction)

    print(">>> Step 2: Textbook returned to warehouse (Reversing COGS and updating inventory asset):")
    event_d_ret = OLPEvent(
        event_id="evt_ret_301",
        idempotency_key="idemp_return_6a5d",
        event_type="goods_returned",
        timestamp="2026-07-22T08:00:00Z",
        amount=10800,
        currency="USD",
        description="Textbook inventory return to warehouse",
        customer_id="cust_alice",
        accounting_context=AccountingContext(
            role="principal",
            product_type="physical",
            recognition="point_in_time"
        ),
        line_items=[
            LineItem(item_id="prod_textbook", price=10000, cogs_estimate=4500)
        ]
    )
    result_d_ret = OLPEngine.compile_event(event_d_ret)
    format_transaction(result_d_ret.initial_transaction)

if __name__ == "__main__":
    run_demo()
