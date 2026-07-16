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

    # =========================================================================
    # DECOUPLED MULTI-PIPELINE RECONCILIATION TEST (PHASE 5)
    # =========================================================================

    def test_decoupled_pipeline_reconciliation(self):
        """
        Verify multi-pipeline reconciliation flow at scale.
        Step 1: Order Placed -> Debit Order Clearing, Credit Gross Rev & Tax
        Step 2: Charge Settled -> Debit Payment Clearing & Processing Fee, Credit Order Clearing
        Step 3: Payout Cleared -> Debit Operating Cash, Credit Payment Clearing
        """
        ctx = AccountingContext(
            role="principal",
            product_type="physical",
            recognition="point_in_time",
            payment_method="card"
        )
        
        # Step 1: Business Side Checkout creates the order log
        order_event = OLPEvent(
            event_id="order_112233",
            event_type="order_placed",
            idempotency_key="idemp_order_112",
            timestamp="2026-07-16T12:00:00Z",
            amount=10800, # $108.00 inclusive of tax
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
        
        # Gross revenue recognized, balance sits in Order Clearing
        self.assertEqual(debits_o[ACCOUNT_PATHS["Order Clearing"]], 10800)
        self.assertEqual(credits_o[ACCOUNT_PATHS["Gross Revenue"]], 10000)
        self.assertEqual(credits_o[ACCOUNT_PATHS["Sales Tax Payable"]], 800)

        # Step 2: Card processor settles payment and takes transaction fee
        settle_event = OLPEvent(
            event_id="settle_112233",
            event_type="charge_settled",
            idempotency_key="idemp_settle_112",
            timestamp="2026-07-16T12:05:00Z",
            amount=10800, # Gross settled value
            processing_fee=320, # $3.20 Stripe fee
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
        
        # Order clearing credited, funds moved to Payment Clearing net of fee
        self.assertEqual(credits_s[ACCOUNT_PATHS["Order Clearing"]], 10800)
        self.assertEqual(debits_s[ACCOUNT_PATHS["Payment Clearing"]], 10480)
        self.assertEqual(debits_s[ACCOUNT_PATHS["Payment Processing Expense"]], 320)

        # Step 3: Treasury processes Stripe bank payout file
        payout_event = OLPEvent(
            event_id="payout_112233",
            event_type="payout_cleared",
            idempotency_key="idemp_payout_112",
            timestamp="2026-07-18T06:00:00Z",
            amount=10480, # Bank deposit matches net payout
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
        
        # Cash debited, Payment clearing credited (zeroed out)
        self.assertEqual(debits_p[ACCOUNT_PATHS["Cash"]], 10480)
        self.assertEqual(credits_p[ACCOUNT_PATHS["Payment Clearing"]], 10480)

if __name__ == "__main__":
    unittest.main()
