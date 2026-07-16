import unittest
from engine import OLPEngine, OLPEvent, AccountingContext, LineItem, LedgerEntry, Transaction, ACCOUNT_PATHS

class TestOLPEngine(unittest.TestCase):
    def test_rule_a_principal_physical_point_in_time(self):
        """
        Scenario 1: Principal sells a physical book for $50.00 (5000 cents) with COGS of $20.00 (2000 cents).
        Should recognize gross revenue immediately and adjust inventory/COGS.
        """
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
        self.assertEqual(tx.idempotency_key, "idemp_001")
        self.assertEqual(tx.status, "posted")
        
        debits = {e.account: e.amount for e in tx.entries if e.type == "debit"}
        credits = {e.account: e.amount for e in tx.entries if e.type == "credit"}
        
        self.assertEqual(debits[ACCOUNT_PATHS["Cash"]], 5000)
        self.assertEqual(credits[ACCOUNT_PATHS["Gross Revenue"]], 5000)
        self.assertEqual(debits[ACCOUNT_PATHS["Cost of Goods Sold"]], 2000)
        self.assertEqual(credits[ACCOUNT_PATHS["Inventory"]], 2000)

    def test_rule_b_principal_digital_saas_over_time(self):
        """
        Scenario 2: Principal sells an annual SaaS subscription for $100.00 (10000 cents).
        Split over 12 months is 833 cents per month, with last month adjusting to 837 cents.
        """
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
            self.assertEqual(amort_tx.idempotency_key, "idemp_002")
            debit_amt = sum(e.amount for e in amort_tx.entries if e.type == "debit")
            if idx < 11:
                self.assertEqual(debit_amt, 833)
            else:
                self.assertEqual(debit_amt, 837)
            total_amortized += debit_amt

        self.assertEqual(total_amortized, 10000)

    def test_tax_and_processing_fee_splits(self):
        """
        Verify VAT/sales tax liabilities and card fees split in cents.
        Customer paid $108.00 (10800 cents) containing $8.00 (800 cents) tax. Gateway fee is $3.20 (320 cents).
        """
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

        # Cash debited should be net of processor fee: 10800 - 320 = 10480
        self.assertEqual(debits[ACCOUNT_PATHS["Cash"]], 10480)
        self.assertEqual(debits[ACCOUNT_PATHS["Payment Processing Expense"]], 320)
        
        # Revenue recognized should be net of tax: 10800 - 800 = 10000
        self.assertEqual(credits[ACCOUNT_PATHS["Gross Revenue"]], 10000)
        self.assertEqual(credits[ACCOUNT_PATHS["Sales Tax Payable"]], 800)

    def test_invoice_and_ar_settlement(self):
        """
        B2B Invoice flow in cents:
        1. Day 1 Invoice: Accounts Receivable vs Gross Revenue + Sales Tax
        2. Day 15 Settlement: Cash + Fee vs Accounts Receivable
        """
        # Day 1: Send Invoice
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

        # Day 15: Receive Payment via Wire (with a $15.00 / 1500 cents transfer fee)
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

        self.assertEqual(debits_set[ACCOUNT_PATHS["Cash"]], 52500) # 54000 - 1500
        self.assertEqual(debits_set[ACCOUNT_PATHS["Payment Processing Expense"]], 1500)
        self.assertEqual(credits_set[ACCOUNT_PATHS["Accounts Receivable"]], 54000)

    def test_refunds_and_inventory_returns(self):
        """
        Verify refund contra-revenue and physical inventory returns (in Cents).
        """
        # 1. Issue a customer refund
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

        # 2. Return physical textbook to inventory
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
        """
        Verify that a global transaction discount is allocated proportionally.
        Book 1: original $30.00 (3000 cents)
        Book 2: original $70.00 (7000 cents)
        Global Discount: $10.00 (1000 cents)
        Allocated net prices: Book 1 = 2700, Book 2 = 6300 (Total net = 9000 cents)
        """
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
