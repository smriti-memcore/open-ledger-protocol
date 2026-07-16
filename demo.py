from engine import OLPEngine, OLPEvent, AccountingContext, LineItem

def format_transaction(tx):
    print("=" * 80)
    print(f"Transaction ID:  {tx.transaction_id}")
    print(f"Source Event:    {tx.source_event_id}")
    print(f"Idempotency Key: {tx.idempotency_key}")
    print(f"Date:            {tx.date}")
    print(f"Status:          {tx.status.upper()}")
    print(f"Consolidation:   {tx.consolidation_type.upper()}")
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

    # -------------------------------------------------------------------------
    # Scenario G: Multinational Subsidiaries and Intercompany Transfers (ASC 810)
    # -------------------------------------------------------------------------
    print("SCENARIO G: Multinational Subsidiaries and Intercompany Transfers (ASC 810).")
    event_g = OLPEvent(
        event_id="evt_cross_border_7788",
        timestamp="2026-07-16T12:00:00Z",
        amount=11900,
        tax_amount=1900,
        tax_jurisdiction="DE",
        currency="EUR",
        description="German checkout with US fulfillment",
        customer_id="cust_helmut",
        intercompany_entity_id="acme_us",
        intercompany_transfer_amount=8500,
        idempotency_key="idemp_cross_border_7788",
        accounting_context=AccountingContext(
            entity_id="acme_de",
            role="principal",
            product_type="digital_download",
            recognition="point_in_time",
            payment_method="card"
        )
    )
    result_g = OLPEngine.compile_event(event_g)
    print(">>> 1. Subsidiary Books (Acme Germany GmbH Ledger - acme_de):")
    format_transaction(result_g.initial_transaction)
    print(">>> 2. Parent Fulfiller Books (Acme US Inc Ledger - acme_us):")
    if result_g.intercompany_transaction:
        format_transaction(result_g.intercompany_transaction)

    # -------------------------------------------------------------------------
    # Scenario H: Brand-Specific Account Pathing Overrides (Audible LOB)
    # -------------------------------------------------------------------------
    print("SCENARIO H: Brand-Specific Account Pathing Overrides (Audible Segment).")
    event_h = OLPEvent(
        event_id="evt_audible_sub_808",
        timestamp="2026-07-16T12:00:00Z",
        amount=1500,
        currency="USD",
        description="Audible Premium Monthly Subscription",
        customer_id="cust_listener_11",
        idempotency_key="idemp_audible_808",
        accounting_context=AccountingContext(
            entity_id="audible_inc",
            segment_id="audible",
            role="principal",
            product_type="digital_saas",
            recognition="over_time",
            term_months=1,
            payment_method="card",
            coa_overrides={
                "Subscription Revenue": "/equity/revenue/audio_subscriptions"
            }
        )
    )
    result_h = OLPEngine.compile_event(event_h)
    print(">>> Initial Booking (Standard asset and deferred accounts):")
    format_transaction(result_h.initial_transaction)
    print(">>> Amortization schedule (routes credit strictly to the custom overridden path):")
    for tx in result_h.amortization_schedule:
        format_transaction(tx)

    # -------------------------------------------------------------------------
    # Scenario I: Intercompany Consolidations & Eliminations (AWS bills Twitch)
    # -------------------------------------------------------------------------
    print("SCENARIO I: Intercompany Consolidations & Eliminations (ASC 810).")
    event_i = OLPEvent(
        event_id="evt_internal_host_900",
        timestamp="2026-07-16T12:00:00Z",
        amount=50000,
        currency="USD",
        description="AWS internal hosting fees billed to Twitch",
        customer_id="cust_twitch_corporate",
        intercompany_entity_id="twitch_corp",
        intercompany_transfer_amount=50000,
        idempotency_key="idemp_internal_host_900",
        accounting_context=AccountingContext(
            entity_id="aws_corp",
            segment_id="aws",
            is_intercompany=True,
            role="principal",
            product_type="digital_download",
            recognition="point_in_time",
            payment_method="card"
        )
    )
    result_i = OLPEngine.compile_event(event_i)
    print(">>> 1. Billing Entity (AWS Ledger - aws_corp):")
    format_transaction(result_i.initial_transaction)
    print(">>> 2. Fulfilling Entity (Twitch Ledger - twitch_corp):")
    if result_i.intercompany_transaction:
        format_transaction(result_i.intercompany_transaction)

    # -------------------------------------------------------------------------
    # Scenario J: Multi-Element Bundle Allocations (Kindle + SaaS)
    # -------------------------------------------------------------------------
    print("SCENARIO J: Multi-Element Bundle Allocations (Kindle + Unlimited Sub - ASC 606).")
    print("Customer buys a Kindle ($100.00 / 10000c - point_in_time) + 3-month SaaS Sub ($30.00 / 3000c - over_time) bundle.")
    print("Gross Price is $130.00 + $13.00 tax = $143.00 (14300c). Processor fee is $3.90 (390c).")
    device_ctx = AccountingContext(role="principal", product_type="physical", recognition="point_in_time")
    sub_ctx = AccountingContext(role="principal", product_type="digital_saas", recognition="over_time", term_months=3)
    
    event_j = OLPEvent(
        event_id="evt_bundle_order_1122",
        timestamp="2026-07-16T12:00:00Z",
        amount=14300,
        tax_amount=1300,
        processing_fee=390,
        currency="USD",
        description="Kindle Reader and Sub Bundle Order",
        customer_id="cust_reader_77",
        idempotency_key="idemp_bundle_order_1122",
        accounting_context=device_ctx,
        line_items=[
            LineItem(item_id="kindle_hardware", price=10000, cogs_estimate=3500), # physical point-in-time
            LineItem(item_id="kindle_unlimited_3mo", price=3000, accounting_context=sub_ctx) # overrides with over-time SaaS
        ]
    )
    result_j = OLPEngine.compile_event(event_j)
    print(">>> Initial Booking (Consolidates point-in-time cash/revenue and over-time deferred liability):")
    format_transaction(result_j.initial_transaction)
    print(">>> Amortization schedule (amortizes subscription portion only):")
    for tx in result_j.amortization_schedule:
        format_transaction(tx)

    # -------------------------------------------------------------------------
    # Scenario K: Sales Returns Reserves & Refund Liabilities (ASC 606)
    # -------------------------------------------------------------------------
    print("SCENARIO K: Sales Returns Reserves & Refund Liabilities (ASC 606).")
    print("Book sold for $100.00 (10000c) with COGS $40.00 (4000c). Returns Reserve expected rate is 3% (300 bps).")
    print("Net revenue = $97.00, Refund Reserve = $3.00. Net COGS = $38.80, Right to Recover Asset = $1.20.")
    event_k = OLPEvent(
        event_id="evt_returns_reserve_01",
        timestamp="2026-07-16T12:00:00Z",
        amount=10000,
        currency="USD",
        description="Book sold with return reserves policy",
        customer_id="cust_student_90",
        expected_return_rate_basis_points=300,
        idempotency_key="idemp_returns_reserve_01",
        accounting_context=AccountingContext(
            role="principal",
            product_type="physical",
            recognition="point_in_time",
            payment_method="card"
        ),
        line_items=[
            LineItem(item_id="hardcover_chemistry", price=10000, cogs_estimate=4000)
        ]
    )
    result_k = OLPEngine.compile_event(event_k)
    format_transaction(result_k.initial_transaction)

    # -------------------------------------------------------------------------
    # Scenario L: Gift Card Lifecycle (Purchases, Redemptions & Breakage)
    # -------------------------------------------------------------------------
    print("SCENARIO L: Gift Card Lifecycle (Purchases, Redemptions & Breakage).")
    gc_ctx = AccountingContext(role="principal", product_type="digital_download", recognition="point_in_time")
    
    print(">>> 1. Customer buys $100.00 Gift Card. Stripe charges $3.00 fee:")
    event_l_buy = OLPEvent(
        event_id="evt_gc_purchase_55",
        event_type="gift_card_purchased",
        timestamp="2026-07-16T12:00:00Z",
        amount=10000,
        processing_fee=300,
        currency="USD",
        description="Store Gift Card $100.00 Purchase",
        customer_id="cust_giftee",
        idempotency_key="idemp_gc_purchase_55",
        accounting_context=gc_ctx
    )
    result_l_buy = OLPEngine.compile_event(event_l_buy)
    format_transaction(result_l_buy.initial_transaction)

    print(">>> 2. Customer redeems $40.00 of the Gift Card balance on books:")
    event_l_red = OLPEvent(
        event_id="evt_gc_redeem_55",
        event_type="gift_card_redeemed",
        timestamp="2026-07-20T14:00:00Z",
        amount=4000,
        currency="USD",
        description="Redeem $40.00 GC balance",
        customer_id="cust_giftee",
        idempotency_key="idemp_gc_redeem_55",
        accounting_context=gc_ctx
    )
    result_l_red = OLPEngine.compile_event(event_l_red)
    format_transaction(result_l_red.initial_transaction)

    print(">>> 3. Customer lets balance expire. Recognize $10.00 GC breakage revenue:")
    event_l_brk = OLPEvent(
        event_id="evt_gc_breakage_55",
        event_type="gift_card_breakage_recognized",
        timestamp="2026-07-30T10:00:00Z",
        amount=1000,
        currency="USD",
        description="Expired gift card breakage sweep",
        customer_id="cust_giftee",
        idempotency_key="idemp_gc_breakage_55",
        accounting_context=gc_ctx
    )
    result_l_brk = OLPEngine.compile_event(event_l_brk)
    format_transaction(result_l_brk.initial_transaction)

if __name__ == "__main__":
    run_demo()
