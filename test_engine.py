import unittest
from engine import OLPEngine, OLPEvent, AccountingContext, LineItem, LedgerEntry, Transaction

class TestOLPEngine(unittest.TestCase):
    def test_rule_a_principal_physical_point_in_time(self):
        """
        Scenario 1: Principal sells a physical book for $50.00 with COGS of $20.00.
        Should recognize gross revenue immediately and adjust inventory/COGS.
        """
        event = OLPEvent(
            event_id="evt_001",
            timestamp="2026-07-16T12:00:00Z",
            amount=50.00,
            currency="USD",
            description="Special Edition hardcover book",
            customer_id="cust_abc",
            accounting_context=AccountingContext(
                role="principal",
                product_type="physical",
                recognition="point_in_time"
            ),
            line_items=[
                LineItem(item_id="prod_book", price=50.00, cogs_estimate=20.00)
            ]
        )

        result = OLPEngine.compile_event(event)
        tx = result.initial_transaction
        self.assertTrue(tx.is_balanced())
        
        debits = {e.account: e.amount for e in tx.entries if e.type == "debit"}
        credits = {e.account: e.amount for e in tx.entries if e.type == "credit"}
        
        self.assertEqual(debits["Cash"], 50.00)
        self.assertEqual(credits["Gross Revenue"], 50.00)
        self.assertEqual(debits["Cost of Goods Sold"], 20.00)
        self.assertEqual(credits["Inventory"], 20.00)

    def test_rule_b_principal_digital_saas_over_time(self):
        """
        Scenario 2: Principal sells an annual SaaS subscription for $100.00.
        """
        event = OLPEvent(
            event_id="evt_002",
            timestamp="2026-07-16T12:00:00Z",
            amount=100.00,
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
        
        self.assertEqual(debits["Cash"], 100.00)
        self.assertEqual(credits["Deferred Revenue"], 100.00)
        
        # Verify amortization schedule
        self.assertEqual(len(result.amortization_schedule), 12)
        total_amortized = 0.0
        
        for idx, amort_tx in enumerate(result.amortization_schedule):
            self.assertTrue(amort_tx.is_balanced())
            debit_amt = sum(e.amount for e in amort_tx.entries if e.type == "debit")
            if idx < 11:
                self.assertEqual(debit_amt, 8.33)
            else:
                self.assertEqual(debit_amt, 8.37)
            total_amortized += debit_amt

        self.assertAlmostEqual(total_amortized, 100.00)

    def test_tax_and_processing_fee_splits(self):
        """
        Verify that OLP splits out VAT/sales tax liabilities and card fees cleanly.
        """
        event = OLPEvent(
            event_id="evt_tax_fees",
            timestamp="2026-07-16T12:00:00Z",
            amount=108.00, # Customer paid $108.00 inclusive of tax
            currency="USD",
            description="Sale with VAT and Card fee",
            customer_id="cust_tax",
            tax_amount=8.00,        # $8.00 is sales tax liability
            processing_fee=3.20,    # $3.20 is card merchant charge
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

        # Cash debited should be net of processor fee: 108.00 - 3.20 = 104.80
        self.assertEqual(debits["Cash"], 104.80)
        self.assertEqual(debits["Payment Processing Expense"], 3.20)
        
        # Revenue recognized should be net of tax: 108.00 - 8.00 = 100.00
        self.assertEqual(credits["Gross Revenue"], 100.00)
        self.assertEqual(credits["Sales Tax Payable"], 8.00)

    def test_invoice_and_ar_settlement(self):
        """
        B2B Invoice flow:
        1. Day 1 Invoice: Accounts Receivable vs Gross Revenue + Sales Tax
        2. Day 15 Settlement: Cash + Fee vs Accounts Receivable
        """
        # Day 1: Send Invoice
        invoice_event = OLPEvent(
            event_id="evt_inv_001",
            timestamp="2026-07-16T12:00:00Z",
            amount=540.00,
            currency="USD",
            description="Enterprise Suite License (Invoice)",
            customer_id="cust_corp",
            tax_amount=40.00,
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

        self.assertEqual(debits["Accounts Receivable"], 540.00)
        self.assertEqual(credits["Gross Revenue"], 500.00)
        self.assertEqual(credits["Sales Tax Payable"], 40.00)

        # Day 15: Receive Payment via Wire (with a $15.00 wire processor fee)
        settle_event = OLPEvent(
            event_id="evt_settle_001",
            event_type="payment_settled",
            timestamp="2026-07-31T09:00:00Z",
            amount=540.00,
            currency="USD",
            description="Wire Payment Settled for Invoice #001",
            customer_id="cust_corp",
            processing_fee=15.00,
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

        self.assertEqual(debits_set["Cash"], 525.00) # 540.00 - 15.00
        self.assertEqual(debits_set["Payment Processing Expense"], 15.00)
        self.assertEqual(credits_set["Accounts Receivable"], 540.00)

    def test_refunds_and_inventory_returns(self):
        """
        Verify refund contra-revenue and physical inventory returns.
        """
        # 1. Issue a customer refund
        refund_event = OLPEvent(
            event_id="evt_refund_001",
            event_type="refund_issued",
            timestamp="2026-07-20T10:00:00Z",
            amount=108.00,
            currency="USD",
            description="Refund for Textbook Order",
            customer_id="cust_alice",
            tax_amount=8.00,
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

        self.assertEqual(debits["Refunds & Allowances"], 100.00)
        self.assertEqual(debits["Sales Tax Payable"], 8.00)
        self.assertEqual(credits["Cash"], 108.00)

        # 2. Return physical textbook to inventory
        return_event = OLPEvent(
            event_id="evt_ret_001",
            event_type="goods_returned",
            timestamp="2026-07-22T08:00:00Z",
            amount=108.00,
            currency="USD",
            description="Textbook returned to warehouse",
            customer_id="cust_alice",
            accounting_context=AccountingContext(
                role="principal",
                product_type="physical",
                recognition="point_in_time"
            ),
            line_items=[
                LineItem(item_id="prod_textbook", price=100.00, cogs_estimate=45.00)
            ]
        )
        res_ret = OLPEngine.compile_event(return_event)
        tx_ret = res_ret.initial_transaction
        self.assertTrue(tx_ret.is_balanced())

        debits_ret = {e.account: e.amount for e in tx_ret.entries if e.type == "debit"}
        credits_ret = {e.account: e.amount for e in tx_ret.entries if e.type == "credit"}

        self.assertEqual(debits_ret["Inventory"], 45.00)
        self.assertEqual(credits_ret["Cost of Goods Sold"], 45.00)

    def test_proportional_discount_allocations(self):
        """
        Verify that a global transaction discount is allocated proportionally to line items.
        Book 1: original $30.00
        Book 2: original $70.00
        Global Discount: $10.00
        Allocated net prices: Book 1 = $27.00, Book 2 = $63.00 (Total net = $90.00)
        """
        event = OLPEvent(
            event_id="evt_discount_001",
            timestamp="2026-07-16T12:00:00Z",
            amount=90.00, # Net transaction price paid
            currency="USD",
            description="Two books with coupon discount",
            customer_id="cust_reader",
            discount_amount=10.00,
            accounting_context=AccountingContext(
                role="principal",
                product_type="physical",
                recognition="point_in_time"
            ),
            line_items=[
                LineItem(item_id="book_1", price=30.00),
                LineItem(item_id="book_2", price=70.00)
            ]
        )
        # compile_event triggers the allocation internally
        result = OLPEngine.compile_event(event)
        
        # Verify line items have been modified with net prices
        items = event.line_items
        self.assertEqual(items[0].price, 27.00) # 30 - 3.00
        self.assertEqual(items[1].price, 63.00) # 70 - 7.00
        self.assertEqual(sum(item.price for item in items), 90.00)

    def test_validation_errors(self):
        with self.assertRaises(ValueError):
            OLPEngine.compile_event(OLPEvent(
                event_id="evt_err",
                timestamp="2026-07-16T12:00:00Z",
                amount=100.00,
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
