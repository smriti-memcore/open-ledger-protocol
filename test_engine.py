import unittest
from engine import OLPEngine, OLPEvent, AccountingContext, LineItem, LedgerEntry, Transaction, ACCOUNT_PATHS

class TestOLPEngine(unittest.TestCase):
    def test_rule_a_principal_physical_point_in_time(self):
        event = OLPEvent(
            event_id="evt_001",
            idempotency_key="idemp_001",
            timestamp="2026-07-16T12:00:00Z",
            amount=5000,
            currency="USD",
            description="Special Edition hardcover book",
            customer_id="cust_abc",
            accounting_context=AccountingContext(
                role="principal",
                product_type="physical",
                recognition="point_in_time"
            ),
            line_items=[
                LineItem(item_id="prod_book", price=5000, cogs_estimate=2000)
            ]
        )

        result = OLPEngine.compile_event(event)
        tx = result.initial_transaction
        self.assertTrue(tx.is_balanced())
        
        debits = {e.account: e.amount for e in tx.entries if e.type == "debit"}
        credits = {e.account: e.amount for e in tx.entries if e.type == "credit"}
        
        self.assertEqual(debits[ACCOUNT_PATHS["Cash"]], 5000)
        self.assertEqual(credits[ACCOUNT_PATHS["Gross Revenue"]], 5000)
        self.assertEqual(debits[ACCOUNT_PATHS["Cost of Goods Sold"]], 2000)
        self.assertEqual(credits[ACCOUNT_PATHS["Inventory"]], 2000)

    def test_rule_b_principal_digital_saas_over_time(self):
        event = OLPEvent(
            event_id="evt_002",
            idempotency_key="idemp_002",
            timestamp="2026-07-16T12:00:00Z",
            amount=10000,
            currency="USD",
            description="Premium SaaS Subscription (Annual)",
            customer_id="cust_def",
            accounting_context=AccountingContext(
                role="principal",
                product_type="digital_saas",
                recognition="over_time",
                term_months=12
            )
        )

        result = OLPEngine.compile_event(event)
        init_tx = result.initial_transaction
        self.assertTrue(init_tx.is_balanced())
        
        debits = {e.account: e.amount for e in init_tx.entries if e.type == "debit"}
        credits = {e.account: e.amount for e in init_tx.entries if e.type == "credit"}
        
        self.assertEqual(debits[ACCOUNT_PATHS["Cash"]], 10000)
        self.assertEqual(credits[ACCOUNT_PATHS["Deferred Revenue"]], 10000)
        
        # Verify amortization schedule
        self.assertEqual(len(result.amortization_schedule), 12)
        total_amortized = 0
        
        for idx, amort_tx in enumerate(result.amortization_schedule):
            self.assertTrue(amort_tx.is_balanced())
            debit_amt = sum(e.amount for e in amort_tx.entries if e.type == "debit")
            if idx < 11:
                self.assertEqual(debit_amt, 833)
            else:
                self.assertEqual(debit_amt, 837)
            total_amortized += debit_amt

        self.assertEqual(total_amortized, 10000)

    def test_tax_and_processing_fee_splits(self):
        event = OLPEvent(
            event_id="evt_tax_fees",
            idempotency_key="idemp_tax",
            timestamp="2026-07-16T12:00:00Z",
            amount=10800,
            currency="USD",
            description="Sale with VAT and Card fee",
            customer_id="cust_tax",
            tax_amount=800,
            processing_fee=320,
            accounting_context=AccountingContext(
                role="principal",
                product_type="digital_download",
                recognition="point_in_time",
                payment_method="card"
            )
        )
        result = OLPEngine.compile_event(event)
        tx = result.initial_transaction
        self.assertTrue(tx.is_balanced())

        debits = {e.account: e.amount for e in tx.entries if e.type == "debit"}
        credits = {e.account: e.amount for e in tx.entries if e.type == "credit"}

        self.assertEqual(debits[ACCOUNT_PATHS["Cash"]], 10480)
        self.assertEqual(debits[ACCOUNT_PATHS["Payment Processing Expense"]], 320)
        self.assertEqual(credits[ACCOUNT_PATHS["Gross Revenue"]], 10000)
        self.assertEqual(credits[ACCOUNT_PATHS["Sales Tax Payable"]], 800)

    def test_invoice_and_ar_settlement(self):
        invoice_event = OLPEvent(
            event_id="evt_inv_001",
            idempotency_key="idemp_inv_001",
            timestamp="2026-07-16T12:00:00Z",
            amount=54000,
            currency="USD",
            description="Enterprise Suite License (Invoice)",
            customer_id="cust_corp",
            tax_amount=4000,
            accounting_context=AccountingContext(
                role="principal",
                product_type="digital_download",
                recognition="point_in_time",
                payment_method="invoice"
            )
        )
        res_inv = OLPEngine.compile_event(invoice_event)
        tx_inv = res_inv.initial_transaction
        self.assertTrue(tx_inv.is_balanced())

        debits = {e.account: e.amount for e in tx_inv.entries if e.type == "debit"}
        credits = {e.account: e.amount for e in tx_inv.entries if e.type == "credit"}

        self.assertEqual(debits[ACCOUNT_PATHS["Accounts Receivable"]], 54000)
        self.assertEqual(credits[ACCOUNT_PATHS["Gross Revenue"]], 50000)
        self.assertEqual(credits[ACCOUNT_PATHS["Sales Tax Payable"]], 4000)

        settle_event = OLPEvent(
            event_id="evt_settle_001",
            idempotency_key="idemp_set_001",
            event_type="payment_settled",
            timestamp="2026-07-31T09:00:00Z",
            amount=54000,
            currency="USD",
            description="Wire Payment Settled for Invoice #001",
            customer_id="cust_corp",
            processing_fee=1500,
            accounting_context=AccountingContext(
                role="principal",
                product_type="digital_download",
                recognition="point_in_time",
                payment_method="invoice"
            )
        )
        res_set = OLPEngine.compile_event(settle_event)
        tx_set = res_set.initial_transaction
        self.assertTrue(tx_set.is_balanced())

        debits_set = {e.account: e.amount for e in tx_set.entries if e.type == "debit"}
        credits_set = {e.account: e.amount for e in tx_set.entries if e.type == "credit"}

        self.assertEqual(debits_set[ACCOUNT_PATHS["Cash"]], 52500)
        self.assertEqual(debits_set[ACCOUNT_PATHS["Payment Processing Expense"]], 1500)
        self.assertEqual(credits_set[ACCOUNT_PATHS["Accounts Receivable"]], 54000)

    def test_refunds_and_inventory_returns(self):
        refund_event = OLPEvent(
            event_id="evt_refund_001",
            idempotency_key="idemp_ref_001",
            event_type="refund_issued",
            timestamp="2026-07-20T10:00:00Z",
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
        res_ref = OLPEngine.compile_event(refund_event)
        tx_ref = res_ref.initial_transaction
        self.assertTrue(tx_ref.is_balanced())

        debits = {e.account: e.amount for e in tx_ref.entries if e.type == "debit"}
        credits = {e.account: e.amount for e in tx_ref.entries if e.type == "credit"}

        self.assertEqual(debits[ACCOUNT_PATHS["Refunds & Allowances"]], 10000)
        self.assertEqual(debits[ACCOUNT_PATHS["Sales Tax Payable"]], 800)
        self.assertEqual(credits[ACCOUNT_PATHS["Cash"]], 10800)

        return_event = OLPEvent(
            event_id="evt_ret_001",
            idempotency_key="idemp_ret_001",
            event_type="goods_returned",
            timestamp="2026-07-22T08:00:00Z",
            amount=10800,
            currency="USD",
            description="Textbook returned to warehouse",
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
        res_ret = OLPEngine.compile_event(return_event)
        tx_ret = res_ret.initial_transaction
        self.assertTrue(tx_ret.is_balanced())

        debits_ret = {e.account: e.amount for e in tx_ret.entries if e.type == "debit"}
        credits_ret = {e.account: e.amount for e in tx_ret.entries if e.type == "credit"}

        self.assertEqual(debits_ret[ACCOUNT_PATHS["Inventory"]], 4500)
        self.assertEqual(credits_ret[ACCOUNT_PATHS["Cost of Goods Sold"]], 4500)

    def test_proportional_discount_allocations(self):
        event = OLPEvent(
            event_id="evt_discount_001",
            idempotency_key="idemp_disc_001",
            timestamp="2026-07-16T12:00:00Z",
            amount=9000,
            currency="USD",
            description="Two books with coupon discount",
            customer_id="cust_reader",
            discount_amount=1000,
            accounting_context=AccountingContext(
                role="principal",
                product_type="physical",
                recognition="point_in_time"
            ),
            line_items=[
                LineItem(item_id="book_1", price=3000),
                LineItem(item_id="book_2", price=7000)
            ]
        )
        result = OLPEngine.compile_event(event)
        
        items = event.line_items
        self.assertEqual(items[0].price, 2700)
        self.assertEqual(items[1].price, 6300)
        self.assertEqual(sum(item.price for item in items), 9000)

    def test_deferred_costs_amortization(self):
        event = OLPEvent(
            event_id="evt_costs_001",
            idempotency_key="idemp_costs_001",
            timestamp="2026-07-16T12:00:00Z",
            amount=3000,
            currency="USD",
            description="3-Month SaaS Sub with Commission Cost",
            customer_id="cust_user",
            capitalized_costs=1200,
            accounting_context=AccountingContext(
                role="principal",
                product_type="digital_saas",
                recognition="over_time",
                term_months=3
            )
        )
        result = OLPEngine.compile_event(event)
        tx = result.initial_transaction
        self.assertTrue(tx.is_balanced())
        
        debits = {e.account: e.amount for e in tx.entries if e.type == "debit"}
        credits = {e.account: e.amount for e in tx.entries if e.type == "credit"}
        
        self.assertEqual(debits[ACCOUNT_PATHS["Deferred Contract Costs"]], 1200)
        self.assertEqual(credits[ACCOUNT_PATHS["Commissions Payable"]], 1200)

        self.assertEqual(len(result.amortization_schedule), 3)
        for amort_tx in result.amortization_schedule:
            self.assertTrue(amort_tx.is_balanced())
            debits_amort = {e.account: e.amount for e in amort_tx.entries if e.type == "debit"}
            credits_amort = {e.account: e.amount for e in amort_tx.entries if e.type == "credit"}
            
            self.assertEqual(debits_amort[ACCOUNT_PATHS["Amortized Commission Expense"]], 400)
            self.assertEqual(credits_amort[ACCOUNT_PATHS["Deferred Contract Costs"]], 400)

    def test_foreign_exchange_revaluation(self):
        settle_event = OLPEvent(
            event_id="evt_fx_settle",
            idempotency_key="idemp_fx_set",
            event_type="payment_settled",
            timestamp="2026-07-31T09:00:00Z",
            amount=54000,
            currency="USD",
            description="Payment Settled with FX Revaluation",
            customer_id="cust_corp",
            processing_fee=1500,
            functional_amount=52000,
            accounting_context=AccountingContext(
                role="principal",
                product_type="digital_download",
                recognition="point_in_time",
                payment_method="invoice"
            )
        )
        result = OLPEngine.compile_event(settle_event)
        tx = result.initial_transaction
        self.assertTrue(tx.is_balanced())

        debits = {e.account: e.amount for e in tx.entries if e.type == "debit"}
        credits = {e.account: e.amount for e in tx.entries if e.type == "credit"}

        self.assertEqual(debits[ACCOUNT_PATHS["Cash"]], 50500)
        self.assertEqual(debits[ACCOUNT_PATHS["Payment Processing Expense"]], 1500)
        self.assertEqual(credits[ACCOUNT_PATHS["Accounts Receivable"]], 54000)
        self.assertEqual(debits[ACCOUNT_PATHS["Loss on FX"]], 2000)

    def test_contract_asset_billing_lifecycle(self):
        event = OLPEvent(
            event_id="evt_unbilled",
            timestamp="2026-07-16T12:00:00Z",
            amount=10000,
            currency="USD",
            description="Unbilled Milestones",
            customer_id="cust_client",
            idempotency_key="idemp_unb",
            accounting_context=AccountingContext(
                role="principal",
                product_type="digital_download",
                recognition="point_in_time",
                payment_method="invoice",
                billing_status="unbilled"
            )
        )
        res = OLPEngine.compile_event(event)
        tx = res.initial_transaction
        self.assertTrue(tx.is_balanced())
        
        debits = {e.account: e.amount for e in tx.entries if e.type == "debit"}
        self.assertEqual(debits[ACCOUNT_PATHS["Contract Assets"]], 10000)

        bill_event = OLPEvent(
            event_id="evt_billed",
            event_type="contract_billed",
            timestamp="2026-07-30T12:00:00Z",
            amount=10000,
            currency="USD",
            description="Billed the unbilled contract asset to AR",
            customer_id="cust_client",
            idempotency_key="idemp_bill",
            accounting_context=AccountingContext(
                role="principal",
                product_type="digital_download",
                recognition="point_in_time"
            )
        )
        res_bill = OLPEngine.compile_event(bill_event)
        tx_bill = res_bill.initial_transaction
        self.assertTrue(tx_bill.is_balanced())
        
        debits_bill = {e.account: e.amount for e in tx_bill.entries if e.type == "debit"}
        credits_bill = {e.account: e.amount for e in tx_bill.entries if e.type == "credit"}
        
        self.assertEqual(debits_bill[ACCOUNT_PATHS["Accounts Receivable"]], 10000)
        self.assertEqual(credits_bill[ACCOUNT_PATHS["Contract Assets"]], 10000)

    def test_bad_debt_write_off(self):
        event = OLPEvent(
            event_id="evt_writeoff",
            event_type="invoice_written_off",
            timestamp="2026-07-25T12:00:00Z",
            amount=5000,
            currency="USD",
            description="Write off default client invoice",
            customer_id="cust_bad",
            idempotency_key="idemp_writeoff",
            accounting_context=AccountingContext(
                role="principal",
                product_type="digital_download",
                recognition="point_in_time"
            )
        )
        res = OLPEngine.compile_event(event)
        tx = res.initial_transaction
        self.assertTrue(tx.is_balanced())
        
        debits = {e.account: e.amount for e in tx.entries if e.type == "debit"}
        credits = {e.account: e.amount for e in tx.entries if e.type == "credit"}
        
        self.assertEqual(debits[ACCOUNT_PATHS["Bad Debt Expense"]], 5000)
        self.assertEqual(credits[ACCOUNT_PATHS["Accounts Receivable"]], 5000)

    def test_decoupled_pipeline_reconciliation(self):
        ctx = AccountingContext(
            role="principal",
            product_type="physical",
            recognition="point_in_time",
            payment_method="card"
        )
        
        order_event = OLPEvent(
            event_id="order_112233",
            event_type="order_placed",
            idempotency_key="idemp_order_112",
            timestamp="2026-07-16T12:00:00Z",
            amount=10800,
            tax_amount=800,
            currency="USD",
            description="Laptop Stand checkout order",
            customer_id="cust_jim",
            accounting_context=ctx
        )
        res_order = OLPEngine.compile_event(order_event)
        tx_order = res_order.initial_transaction
        self.assertTrue(tx_order.is_balanced())
        
        debits_o = {e.account: e.amount for e in tx_order.entries if e.type == "debit"}
        credits_o = {e.account: e.amount for e in tx_order.entries if e.type == "credit"}
        
        self.assertEqual(debits_o[ACCOUNT_PATHS["Order Clearing"]], 10800)
        self.assertEqual(credits_o[ACCOUNT_PATHS["Gross Revenue"]], 10000)
        self.assertEqual(credits_o[ACCOUNT_PATHS["Sales Tax Payable"]], 800)

        settle_event = OLPEvent(
            event_id="settle_112233",
            event_type="charge_settled",
            idempotency_key="idemp_settle_112",
            timestamp="2026-07-16T12:05:00Z",
            amount=10800,
            processing_fee=320,
            currency="USD",
            description="Stripe charge settlement for order 112233",
            customer_id="cust_jim",
            accounting_context=ctx
        )
        res_settle = OLPEngine.compile_event(settle_event)
        tx_settle = res_settle.initial_transaction
        self.assertTrue(tx_settle.is_balanced())
        
        debits_s = {e.account: e.amount for e in tx_settle.entries if e.type == "debit"}
        credits_s = {e.account: e.amount for e in tx_settle.entries if e.type == "credit"}
        
        self.assertEqual(credits_s[ACCOUNT_PATHS["Order Clearing"]], 10800)
        self.assertEqual(debits_s[ACCOUNT_PATHS["Payment Clearing"]], 10480)
        self.assertEqual(debits_s[ACCOUNT_PATHS["Payment Processing Expense"]], 320)

        payout_event = OLPEvent(
            event_id="payout_112233",
            event_type="payout_cleared",
            idempotency_key="idemp_payout_112",
            timestamp="2026-07-18T06:00:00Z",
            amount=10480,
            currency="USD",
            description="Bank transfer payout from Stripe",
            customer_id="cust_jim",
            accounting_context=ctx
        )
        res_payout = OLPEngine.compile_event(payout_event)
        tx_payout = res_payout.initial_transaction
        self.assertTrue(tx_payout.is_balanced())
        
        debits_p = {e.account: e.amount for e in tx_payout.entries if e.type == "debit"}
        credits_p = {e.account: e.amount for e in tx_payout.entries if e.type == "credit"}
        
        self.assertEqual(debits_p[ACCOUNT_PATHS["Cash"]], 10480)
        self.assertEqual(credits_p[ACCOUNT_PATHS["Payment Clearing"]], 10480)

    def test_multinational_tax_jurisdictions(self):
        event = OLPEvent(
            event_id="evt_de_sale",
            idempotency_key="idemp_de_sale",
            timestamp="2026-07-16T12:00:00Z",
            amount=11900,
            tax_amount=1900,
            tax_jurisdiction="DE",
            currency="EUR",
            description="Sale to German client",
            customer_id="cust_helmut",
            accounting_context=AccountingContext(
                entity_id="acme_de",
                role="principal",
                product_type="digital_download",
                recognition="point_in_time"
            )
        )
        result = OLPEngine.compile_event(event)
        tx = result.initial_transaction
        self.assertTrue(tx.is_balanced())
        
        credits = {e.account: e.amount for e in tx.entries if e.type == "credit"}
        
        self.assertEqual(credits["/liabilities/tax/payable/de"], 1900)
        self.assertEqual(credits[ACCOUNT_PATHS["Gross Revenue"]], 10000)

    def test_intercompany_transfer_pricing(self):
        event = OLPEvent(
            event_id="evt_cross_border",
            idempotency_key="idemp_cross_border",
            timestamp="2026-07-16T12:00:00Z",
            amount=11900,
            tax_amount=1900,
            tax_jurisdiction="DE",
            currency="EUR",
            description="Acme Germany sells, Acme US fulfills",
            customer_id="cust_helmut",
            intercompany_entity_id="acme_us",
            intercompany_transfer_amount=8500,
            accounting_context=AccountingContext(
                entity_id="acme_de",
                role="principal",
                product_type="digital_download",
                recognition="point_in_time"
            )
        )
        result = OLPEngine.compile_event(event)
        
        tx_de = result.initial_transaction
        self.assertTrue(tx_de.is_balanced())
        debits_de = {e.account: e.amount for e in tx_de.entries if e.type == "debit"}
        credits_de = {e.account: e.amount for e in tx_de.entries if e.type == "credit"}
        
        self.assertEqual(debits_de[ACCOUNT_PATHS["Intercompany Expense"]], 8500)
        self.assertEqual(credits_de["/liabilities/payables/intercompany_acme_us"], 8500)

        tx_us = result.intercompany_transaction
        self.assertIsNotNone(tx_us)
        self.assertTrue(tx_us.is_balanced())
        
        debits_us = {e.account: e.amount for e in tx_us.entries if e.type == "debit"}
        credits_us = {e.account: e.amount for e in tx_us.entries if e.type == "credit"}
        
        self.assertEqual(debits_us["/assets/receivables/intercompany_acme_de"], 8500)
        self.assertEqual(credits_us[ACCOUNT_PATHS["Intercompany Revenue"]], 8500)

    def test_operating_segment_and_consolidation_elimination(self):
        event = OLPEvent(
            event_id="evt_internal_aws_bill",
            idempotency_key="idemp_internal_123",
            timestamp="2026-07-16T12:00:00Z",
            amount=50000,
            currency="USD",
            description="AWS cloud compute hosting invoice for Twitch",
            customer_id="cust_twitch_corp",
            intercompany_entity_id="twitch_corp",
            intercompany_transfer_amount=50000,
            accounting_context=AccountingContext(
                entity_id="aws_corp",
                segment_id="aws",
                is_intercompany=True,
                role="principal",
                product_type="digital_download",
                recognition="point_in_time"
            )
        )
        result = OLPEngine.compile_event(event)
        
        tx_primary = result.initial_transaction
        tx_ic = result.intercompany_transaction
        
        self.assertTrue(tx_primary.is_balanced())
        self.assertTrue(tx_ic.is_balanced())
        
        self.assertEqual(tx_primary.consolidation_type, "elimination")
        self.assertEqual(tx_ic.consolidation_type, "elimination")

    def test_dynamic_chart_of_accounts_overrides(self):
        event = OLPEvent(
            event_id="evt_audible_sub",
            idempotency_key="idemp_audible_998",
            timestamp="2026-07-16T12:00:00Z",
            amount=1500,
            currency="USD",
            description="Audible Monthly Subscription",
            customer_id="cust_listener",
            accounting_context=AccountingContext(
                entity_id="audible_inc",
                segment_id="audible",
                role="principal",
                product_type="digital_saas",
                recognition="over_time",
                term_months=1,
                coa_overrides={
                    "Subscription Revenue": "/equity/revenue/audio_subscriptions"
                }
            )
        )
        result = OLPEngine.compile_event(event)
        
        self.assertEqual(len(result.amortization_schedule), 1)
        amort_tx = result.amortization_schedule[0]
        self.assertTrue(amort_tx.is_balanced())
        
        credits = {e.account: e.amount for e in amort_tx.entries if e.type == "credit"}
        self.assertIn("/equity/revenue/audio_subscriptions", credits)
        self.assertEqual(credits["/equity/revenue/audio_subscriptions"], 1500)

    def test_line_item_context_overrides_bundle(self):
        device_ctx = AccountingContext(
            role="principal",
            product_type="physical",
            recognition="point_in_time"
        )
        sub_ctx = AccountingContext(
            role="principal",
            product_type="digital_saas",
            recognition="over_time",
            term_months=5
        )
        
        event = OLPEvent(
            event_id="evt_bundle_pos",
            idempotency_key="idemp_bundle_pos",
            timestamp="2026-07-16T12:00:00Z",
            amount=16500,
            tax_amount=1500,
            processing_fee=450,
            currency="USD",
            description="Kindle + Subscription Bundle Checkout",
            customer_id="cust_reader",
            accounting_context=device_ctx,
            line_items=[
                LineItem(item_id="kindle_device", price=10000, cogs_estimate=3000),
                LineItem(item_id="kindle_unlimited_sub", price=5000, accounting_context=sub_ctx)
            ]
        )
        
        result = OLPEngine.compile_event(event)
        init_tx = result.initial_transaction
        self.assertTrue(init_tx.is_balanced())
        
        debits = {e.account: e.amount for e in init_tx.entries if e.type == "debit"}
        credits = {e.account: e.amount for e in init_tx.entries if e.type == "credit"}
        
        self.assertEqual(debits[ACCOUNT_PATHS["Cash"]], 16050)
        self.assertEqual(debits[ACCOUNT_PATHS["Payment Processing Expense"]], 450)
        self.assertEqual(credits[ACCOUNT_PATHS["Gross Revenue"]], 10000)
        self.assertEqual(credits[ACCOUNT_PATHS["Deferred Revenue"]], 5000)
        self.assertEqual(debits[ACCOUNT_PATHS["Cost of Goods Sold"]], 3000)

        self.assertEqual(len(result.amortization_schedule), 5)
        for tx in result.amortization_schedule:
            self.assertTrue(tx.is_balanced())
            debs = {e.account: e.amount for e in tx.entries if e.type == "debit"}
            creds = {e.account: e.amount for e in tx.entries if e.type == "credit"}
            self.assertEqual(debs[ACCOUNT_PATHS["Deferred Revenue"]], 1000)
            self.assertEqual(creds[ACCOUNT_PATHS["Subscription Revenue"]], 1000)

    def test_sales_returns_reserves(self):
        event = OLPEvent(
            event_id="evt_reserve_pos",
            idempotency_key="idemp_reserve_pos",
            timestamp="2026-07-16T12:00:00Z",
            amount=10000,
            currency="USD",
            description="Book sale with expected 3% returns reserve",
            customer_id="cust_student",
            expected_return_rate_basis_points=300,
            accounting_context=AccountingContext(
                role="principal",
                product_type="physical",
                recognition="point_in_time"
            ),
            line_items=[
                LineItem(item_id="hardcover_textbook", price=10000, cogs_estimate=4000)
            ]
        )
        result = OLPEngine.compile_event(event)
        tx = result.initial_transaction
        self.assertTrue(tx.is_balanced())
        
        debits = {e.account: e.amount for e in tx.entries if e.type == "debit"}
        credits = {e.account: e.amount for e in tx.entries if e.type == "credit"}
        
        self.assertEqual(credits[ACCOUNT_PATHS["Gross Revenue"]], 9700)
        self.assertEqual(credits[ACCOUNT_PATHS["Refund Reserve"]], 300)
        self.assertEqual(debits[ACCOUNT_PATHS["Cost of Goods Sold"]], 3880)
        self.assertEqual(debits[ACCOUNT_PATHS["Right to Recover"]], 120)
        self.assertEqual(credits[ACCOUNT_PATHS["Inventory"]], 4000)

    def test_gift_card_lifecycle(self):
        ctx = AccountingContext(
            role="principal",
            product_type="digital_download",
            recognition="point_in_time"
        )
        
        buy_event = OLPEvent(
            event_id="gc_buy_1",
            idempotency_key="idemp_gc_buy_1",
            event_type="gift_card_purchased",
            timestamp="2026-07-16T12:00:00Z",
            amount=10000,
            currency="USD",
            description="Buy $100 store gift card",
            customer_id="cust_gifting",
            processing_fee=300,
            accounting_context=ctx
        )
        res_buy = OLPEngine.compile_event(buy_event)
        tx_buy = res_buy.initial_transaction
        self.assertTrue(tx_buy.is_balanced())
        
        debits_b = {e.account: e.amount for e in tx_buy.entries if e.type == "debit"}
        credits_b = {e.account: e.amount for e in tx_buy.entries if e.type == "credit"}
        
        self.assertEqual(debits_b[ACCOUNT_PATHS["Cash"]], 9700)
        self.assertEqual(debits_b[ACCOUNT_PATHS["Payment Processing Expense"]], 300)
        self.assertEqual(credits_b[ACCOUNT_PATHS["Gift Card Liability"]], 10000)

        redeem_event = OLPEvent(
            event_id="gc_red_1",
            idempotency_key="idemp_gc_red_1",
            event_type="gift_card_redeemed",
            timestamp="2026-07-20T12:00:00Z",
            amount=4000,
            currency="USD",
            description="Redeem $40 gift card balance on books",
            customer_id="cust_gifting",
            accounting_context=ctx
        )
        res_red = OLPEngine.compile_event(redeem_event)
        tx_red = res_red.initial_transaction
        self.assertTrue(tx_red.is_balanced())
        
        debits_r = {e.account: e.amount for e in tx_red.entries if e.type == "debit"}
        credits_r = {e.account: e.amount for e in tx_red.entries if e.type == "credit"}
        
        self.assertEqual(debits_r[ACCOUNT_PATHS["Gift Card Liability"]], 4000)
        self.assertEqual(credits_r[ACCOUNT_PATHS["Gross Revenue"]], 4000)

        breakage_event = OLPEvent(
            event_id="gc_brk_1",
            idempotency_key="idemp_gc_brk_1",
            event_type="gift_card_breakage_recognized",
            timestamp="2026-07-30T12:00:00Z",
            amount=1000,
            currency="USD",
            description="Recognize $10 gift card expiration breakage",
            customer_id="cust_gifting",
            accounting_context=ctx
        )
        res_brk = OLPEngine.compile_event(breakage_event)
        tx_brk = res_brk.initial_transaction
        self.assertTrue(tx_brk.is_balanced())
        
        debits_brk = {e.account: e.amount for e in tx_brk.entries if e.type == "debit"}
        credits_brk = {e.account: e.amount for e in tx_brk.entries if e.type == "credit"}
        
        self.assertEqual(debits_brk[ACCOUNT_PATHS["Gift Card Liability"]], 1000)
        self.assertEqual(credits_brk[ACCOUNT_PATHS["Gift Card Breakage"]], 1000)

    # =========================================================================
    # POST-TRANSACTION ADJUSTMENTS AND VOIDS TESTS (PHASE 9)
    # =========================================================================

    def test_retroactive_revenue_adjustment(self):
        """
        ASC 606 Variable consideration: Retroactive revenue reduction of $10.00 (1000c).
        """
        event = OLPEvent(
            event_id="evt_rev_adj_99",
            idempotency_key="idemp_rev_adj_99",
            event_type="revenue_adjustment_posted",
            timestamp="2026-07-20T12:00:00Z",
            amount=1000,
            currency="USD",
            description="Post-billing volume rebate adjustment",
            customer_id="cust_client_corp",
            accounting_context=AccountingContext(
                role="principal",
                product_type="digital_download",
                recognition="point_in_time",
                payment_method="invoice"
            )
        )
        result = OLPEngine.compile_event(event)
        tx = result.initial_transaction
        self.assertTrue(tx.is_balanced())
        
        debits = {e.account: e.amount for e in tx.entries if e.type == "debit"}
        credits = {e.account: e.amount for e in tx.entries if e.type == "credit"}
        
        self.assertEqual(debits[ACCOUNT_PATHS["Refunds & Allowances"]], 1000)
        self.assertEqual(credits[ACCOUNT_PATHS["Accounts Receivable"]], 1000)

    def test_invoice_voided(self):
        """
        Invoice Voided: reverse $540.00 (54000c inclusive of $40.00 tax).
        """
        event = OLPEvent(
            event_id="evt_void_invoice",
            idempotency_key="idemp_void_invoice",
            event_type="invoice_voided",
            timestamp="2026-07-17T09:00:00Z",
            amount=54000,
            tax_amount=4000,
            currency="USD",
            description="Void invoice #908 issued in error",
            customer_id="cust_bigcorp",
            accounting_context=AccountingContext(
                role="principal",
                product_type="digital_download",
                recognition="point_in_time",
                payment_method="invoice"
            )
        )
        result = OLPEngine.compile_event(event)
        tx = result.initial_transaction
        self.assertTrue(tx.is_balanced())
        
        debits = {e.account: e.amount for e in tx.entries if e.type == "debit"}
        credits = {e.account: e.amount for e in tx.entries if e.type == "credit"}
        
        self.assertEqual(debits[ACCOUNT_PATHS["Gross Revenue"]], 50000)
        self.assertEqual(debits[ACCOUNT_PATHS["Sales Tax Payable"]], 4000)
        self.assertEqual(credits[ACCOUNT_PATHS["Accounts Receivable"]], 54000)

    def test_accrual_reversed(self):
        """
        Accrual reversed: Debit AP (Vendor) and Credit Revenue / Cost.
        """
        event = OLPEvent(
            event_id="evt_accrual_rev",
            idempotency_key="idemp_accrual_rev",
            event_type="accrual_reversed",
            timestamp="2026-07-20T12:00:00Z",
            amount=8000,
            currency="USD",
            description="Reverse over-accrued vendor payables",
            customer_id="vendor_xyz",
            accounting_context=AccountingContext(
                role="agent",
                product_type="physical",
                recognition="point_in_time"
            )
        )
        result = OLPEngine.compile_event(event)
        tx = result.initial_transaction
        self.assertTrue(tx.is_balanced())
        
        debits = {e.account: e.amount for e in tx.entries if e.type == "debit"}
        credits = {e.account: e.amount for e in tx.entries if e.type == "credit"}
        
        self.assertEqual(debits[ACCOUNT_PATHS["Accounts Payable (Vendor)"]], 8000)
        self.assertEqual(credits[ACCOUNT_PATHS["Gross Revenue"]], 8000)

    def test_validation_errors(self):
        with self.assertRaises(ValueError):
            OLPEngine.compile_event(OLPEvent(
                event_id="evt_err",
                idempotency_key="idemp_err",
                timestamp="2026-07-16T12:00:00Z",
                amount=10000,
                currency="USD",
                description="Error Sub",
                customer_id="cust_err",
                accounting_context=AccountingContext(
                    role="principal",
                    product_type="digital_saas",
                    recognition="over_time"
                )
            ))

if __name__ == "__main__":
    unittest.main()
