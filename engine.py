import uuid
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Optional

@dataclass
class AccountingContext:
    role: str                       # "principal" | "agent"
    product_type: str               # "physical" | "digital_saas" | "digital_download"
    recognition: str                # "point_in_time" | "over_time"
    entity_id: str = "default_entity"  # MNC legal entity identifier
    segment_id: Optional[str] = None   # Operating segment / LOB tag (ASC 280)
    is_intercompany: bool = False      # Intercompany consolidation elimination flag (ASC 810)
    term_months: Optional[int] = None
    platform_fee_percent: float = 0.20
    payment_method: str = "card"    # "card" | "invoice"
    billing_status: str = "billed"  # "billed" | "unbilled"
    coa_overrides: dict = field(default_factory=dict) # Per-brand chart overrides

@dataclass
class LineItem:
    item_id: str
    price: int                      # In cents
    cogs_estimate: int = 0          # In cents
    accounting_context: Optional[AccountingContext] = None # Line-level overrides (ASC 606 Bundles)

@dataclass
class OLPEvent:
    event_id: str
    timestamp: str
    amount: int                     # In cents
    currency: str
    description: str
    customer_id: str
    accounting_context: AccountingContext
    idempotency_key: str            # Required to prevent double-posting
    event_type: str = "immediate_sale"
    tax_amount: int = 0             # In cents
    tax_jurisdiction: Optional[str] = None # Local tax region (e.g. "DE", "US-CA")
    processing_fee: int = 0         # In cents
    discount_amount: int = 0        # In cents
    capitalized_costs: int = 0      # In cents
    functional_amount: Optional[int] = None
    expected_return_rate_basis_points: int = 0 # expected returns reserve rate (ASC 606, e.g. 300 = 3%)
    intercompany_entity_id: Optional[str] = None # Partner entity fulfilling order (ASC 810)
    intercompany_transfer_amount: int = 0        # Transfer pricing fee in cents
    line_items: List[LineItem] = field(default_factory=list)

@dataclass
class LedgerEntry:
    account: str                    # Standardized path string
    type: str                       # "debit" | "credit"
    amount: int                     # In cents

@dataclass
class Transaction:
    transaction_id: str
    source_event_id: str
    idempotency_key: str
    date: str
    description: str
    status: str = "posted"          # "pending" | "posted"
    consolidation_type: str = "standard" # "standard" | "elimination" (ASC 810)
    entries: List[LedgerEntry] = field(default_factory=list)

    def is_balanced(self) -> bool:
        debits = sum(e.amount for e in self.entries if e.type == "debit")
        credits = sum(e.amount for e in self.entries if e.type == "credit")
        return debits == credits

@dataclass
class CompilationResult:
    initial_transaction: Transaction
    amortization_schedule: List[Transaction] = field(default_factory=list)
    intercompany_transaction: Optional[Transaction] = None # Balances on the partner entity ledger

# Chart of Accounts mappings
ACCOUNT_PATHS = {
    "Cash": "/assets/liquid/cash",
    "Accounts Receivable": "/assets/receivables/ar",
    "Contract Assets": "/assets/receivables/contract_assets",
    "Order Clearing": "/assets/receivables/order_clearing",
    "Payment Clearing": "/assets/receivables/payment_clearing",
    "Right to Recover": "/assets/receivables/right_to_recover",
    "Inventory": "/assets/inventory",
    "Deferred Contract Costs": "/assets/deferred_costs/commissions",
    "Deferred Revenue": "/liabilities/deferred/revenue",
    "Deferred Payable (Vendor)": "/liabilities/deferred/payable_vendor",
    "Deferred Commission Revenue": "/liabilities/deferred/commission",
    "Accounts Payable (Vendor)": "/liabilities/payables/vendor",
    "Sales Tax Payable": "/liabilities/tax/payable",
    "Commissions Payable": "/liabilities/payables/commissions",
    "Refund Reserve": "/liabilities/refund_reserve",
    "Gift Card Liability": "/liabilities/gift_card",
    "Gross Revenue": "/equity/revenue/gross",
    "Subscription Revenue": "/equity/revenue/subscription",
    "Commission Revenue": "/equity/revenue/commission",
    "Intercompany Revenue": "/equity/revenue/intercompany",
    "Gift Card Breakage": "/equity/revenue/breakage",
    "Refunds & Allowances": "/equity/revenue/refunds_allowances",
    "Gain on FX": "/equity/gain_fx",
    "Payment Processing Expense": "/expenses/processing/fees",
    "Cost of Goods Sold": "/expenses/cogs",
    "Amortized Commission Expense": "/expenses/commissions",
    "Bad Debt Expense": "/expenses/bad_debt",
    "Loss on FX": "/expenses/fx_loss",
    "Intercompany Expense": "/expenses/intercompany"
}

class OLPEngine:
    @staticmethod
    def _allocate_discounts(event: OLPEvent) -> OLPEvent:
        if event.discount_amount <= 0 or not event.line_items:
            return event
            
        total_price = sum(item.price for item in event.line_items)
        if total_price <= 0:
            return event

        new_items = []
        accum_discount = 0
        n_items = len(event.line_items)

        for idx, item in enumerate(event.line_items):
            if idx == n_items - 1:
                current_discount = event.discount_amount - accum_discount
            else:
                current_discount = (event.discount_amount * item.price) // total_price
                accum_discount += current_discount

            new_price = max(0, item.price - current_discount)
            new_items.append(LineItem(
                item_id=item.item_id,
                price=new_price,
                cogs_estimate=item.cogs_estimate,
                accounting_context=item.accounting_context
            ))
            
        event.line_items = new_items
        return event

    @staticmethod
    def _get_account_path(event: OLPEvent, default_key: str) -> str:
        ctx = event.accounting_context
        if ctx.coa_overrides and default_key in ctx.coa_overrides:
            return ctx.coa_overrides[default_key]
        return ACCOUNT_PATHS[default_key]

    @staticmethod
    def _get_tax_account(event: OLPEvent) -> str:
        if event.tax_jurisdiction:
            clean_jurisdiction = event.tax_jurisdiction.lower().replace("-", "_")
            return f"/liabilities/tax/payable/{clean_jurisdiction}"
        return OLPEngine._get_account_path(event, "Sales Tax Payable")

    @staticmethod
    def _get_debit_asset_account(event: OLPEvent) -> str:
        ctx = event.accounting_context
        if ctx.payment_method == "invoice":
            if ctx.billing_status == "unbilled":
                return OLPEngine._get_account_path(event, "Contract Assets")
            return OLPEngine._get_account_path(event, "Accounts Receivable")
        return OLPEngine._get_account_path(event, "Cash")

    @staticmethod
    def compile_event(event: OLPEvent) -> CompilationResult:
        event = OLPEngine._allocate_discounts(event)
        ctx = event.accounting_context

        # Check validation rules
        if ctx.recognition == "over_time" and (ctx.term_months is None or ctx.term_months <= 0):
            raise ValueError("term_months must be >= 1 for over_time recognition")
        for item in event.line_items:
            if item.accounting_context and item.accounting_context.recognition == "over_time" and (item.accounting_context.term_months is None or item.accounting_context.term_months <= 0):
                raise ValueError("term_months must be >= 1 for line item over_time recognition")

        # Check for Line-Item level overrides (ASC 606 bundles)
        has_line_overrides = any(item.accounting_context is not None for item in event.line_items)
        if has_line_overrides and event.event_type not in (
            "payment_settled", "refund_issued", "goods_returned", 
            "contract_billed", "invoice_written_off", "gift_card_purchased",
            "gift_card_redeemed", "gift_card_breakage_recognized",
            "revenue_adjustment_posted", "invoice_voided", "accrual_reversed"
        ):
            return OLPEngine._compile_split_bundle(event)

        # Route standard event types
        if event.event_type == "gift_card_purchased":
            return OLPEngine._compile_gift_card_purchased(event)
        elif event.event_type == "gift_card_redeemed":
            return OLPEngine._compile_gift_card_redeemed(event)
        elif event.event_type == "gift_card_breakage_recognized":
            return OLPEngine._compile_gift_card_breakage(event)
        elif event.event_type == "revenue_adjustment_posted":
            res = OLPEngine._compile_revenue_adjustment(event)
        elif event.event_type == "invoice_voided":
            res = OLPEngine._compile_invoice_voided(event)
        elif event.event_type == "accrual_reversed":
            res = OLPEngine._compile_accrual_reversed(event)
        elif event.event_type == "payment_settled":
            res = OLPEngine._compile_payment_settled(event)
        elif event.event_type == "refund_issued":
            res = OLPEngine._compile_refund_issued(event)
        elif event.event_type == "goods_returned":
            # total_cogs
            total_cogs = sum(item.cogs_estimate for item in event.line_items)
            res = OLPEngine._compile_goods_returned(event, total_cogs)
        elif event.event_type == "contract_billed":
            res = OLPEngine._compile_contract_billed(event)
        elif event.event_type == "invoice_written_off":
            res = OLPEngine._compile_invoice_written_off(event)
        elif event.event_type == "order_placed":
            res = OLPEngine._compile_order_placed(event)
        elif event.event_type == "charge_settled":
            res = OLPEngine._compile_charge_settled(event)
        elif event.event_type == "payout_cleared":
            res = OLPEngine._compile_payout_cleared(event)
        elif ctx.role == "principal":
            total_cogs = sum(item.cogs_estimate for item in event.line_items)
            if ctx.recognition == "point_in_time":
                res = OLPEngine._compile_principal_pit(event, total_cogs)
            else:
                res = OLPEngine._compile_principal_ot(event)
        else: # agent
            if ctx.recognition == "point_in_time":
                res = OLPEngine._compile_agent_pit(event)
            else:
                res = OLPEngine._compile_agent_ot(event)

        # Apply Intercompany Transfer (ASC 810)
        if event.intercompany_entity_id and event.intercompany_entity_id != ctx.entity_id:
            pay_acct = f"/liabilities/payables/intercompany_{event.intercompany_entity_id.lower()}"
            res.initial_transaction.entries.append(
                LedgerEntry(account=OLPEngine._get_account_path(event, "Intercompany Expense"), type="debit", amount=event.intercompany_transfer_amount)
            )
            res.initial_transaction.entries.append(
                LedgerEntry(account=pay_acct, type="credit", amount=event.intercompany_transfer_amount)
            )
            
            rec_acct = f"/assets/receivables/intercompany_{ctx.entity_id.lower()}"
            partner_tx = Transaction(
                transaction_id=f"tx_ic_{uuid.uuid4().hex[:8]}",
                source_event_id=event.event_id,
                idempotency_key=f"{event.idempotency_key}_ic",
                date=event.timestamp,
                status="posted",
                consolidation_type="elimination" if ctx.is_intercompany else "standard",
                description=f"OLP Intercompany Revenue Transfer: {ctx.entity_id} to {event.intercompany_entity_id}",
                entries=[
                    LedgerEntry(account=rec_acct, type="debit", amount=event.intercompany_transfer_amount),
                    LedgerEntry(account=OLPEngine._get_account_path(event, "Intercompany Revenue"), type="credit", amount=event.intercompany_transfer_amount)
                ]
            )
            res.intercompany_transaction = partner_tx

        # Set consolidation tags
        if ctx.is_intercompany:
            res.initial_transaction.consolidation_type = "elimination"
            if res.amortization_schedule:
                for tx in res.amortization_schedule:
                    tx.consolidation_type = "elimination"
            if res.intercompany_transaction:
                res.intercompany_transaction.consolidation_type = "elimination"

        return res

    @staticmethod
    def _compile_split_bundle(event: OLPEvent) -> CompilationResult:
        """
        ASC 606 Step 4: Multi-element bundle allocation compilation.
        Converts the single event into localized line-item events, compiles each, and aggregates.
        """
        total_price = sum(item.price for item in event.line_items)
        if total_price <= 0:
            raise ValueError("Total bundle price must be > 0")

        consolidated_entries = []
        amort_by_date = {}
        
        accum_tax = 0
        accum_fee = 0
        n_items = len(event.line_items)

        for idx, item in enumerate(event.line_items):
            # Proportional splits of tax and fee
            if idx == n_items - 1:
                item_tax = event.tax_amount - accum_tax
                item_fee = event.processing_fee - accum_fee
            else:
                item_tax = (event.tax_amount * item.price) // total_price
                item_fee = (event.processing_fee * item.price) // total_price
                accum_tax += item_tax
                accum_fee += item_fee

            # Context resolution: localized override falls back to global context
            item_ctx = item.accounting_context if item.accounting_context is not None else event.accounting_context
            
            # Form mini-event payload
            item_without_override = LineItem(
                item_id=item.item_id,
                price=item.price,
                cogs_estimate=item.cogs_estimate,
                accounting_context=None
            )
            item_event = OLPEvent(
                event_id=event.event_id,
                timestamp=event.timestamp,
                amount=item.price + item_tax,
                currency=event.currency,
                description=f"Bundle Item: {item.item_id}",
                customer_id=event.customer_id,
                accounting_context=item_ctx,
                idempotency_key=event.idempotency_key,
                event_type=event.event_type,
                tax_amount=item_tax,
                tax_jurisdiction=event.tax_jurisdiction,
                processing_fee=item_fee,
                discount_amount=0,
                expected_return_rate_basis_points=event.expected_return_rate_basis_points,
                line_items=[item_without_override]
            )

            # Compile mini-event
            item_res = OLPEngine.compile_event(item_event)
            
            # Merge initial transaction entries
            consolidated_entries.extend(item_res.initial_transaction.entries)

            # Merge monthly amortization entries
            for amort_tx in item_res.amortization_schedule:
                d = amort_tx.date
                if d not in amort_by_date:
                    amort_by_date[d] = []
                amort_by_date[d].extend(amort_tx.entries)

        # Net consolidated entries by (account, type)
        netted_entries = {}
        for entry in consolidated_entries:
            key = (entry.account, entry.type)
            netted_entries[key] = netted_entries.get(key, 0) + entry.amount
        consolidated_entries = [LedgerEntry(account=k[0], type=k[1], amount=v) for k, v in netted_entries.items()]

        # 1. Build Consolidated Initial Transaction
        init_tx = Transaction(
            transaction_id=f"tx_bundle_init_{uuid.uuid4().hex[:8]}",
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            description=f"OLP Bundle Initial booking: {event.description}",
            status="posted",
            consolidation_type="elimination" if event.accounting_context.is_intercompany else "standard",
            entries=consolidated_entries
        )

        # 2. Build Consolidated Amortization Schedule
        amort_schedule = []
        for index, d in enumerate(sorted(amort_by_date.keys()), 1):
            netted_amort = {}
            for entry in amort_by_date[d]:
                key = (entry.account, entry.type)
                netted_amort[key] = netted_amort.get(key, 0) + entry.amount
            amort_entries = [LedgerEntry(account=k[0], type=k[1], amount=v) for k, v in netted_amort.items()]
            tx_amort = Transaction(
                transaction_id=f"tx_bundle_amort_{index}_{uuid.uuid4().hex[:8]}",
                source_event_id=event.event_id,
                idempotency_key=event.idempotency_key,
                date=d,
                description=f"OLP Bundle Amortization Month {index}: {event.description}",
                status="posted",
                consolidation_type="elimination" if event.accounting_context.is_intercompany else "standard",
                entries=amort_entries
            )
            amort_schedule.append(tx_amort)

        return CompilationResult(initial_transaction=init_tx, amortization_schedule=amort_schedule)

    @staticmethod
    def _compile_gift_card_purchased(event: OLPEvent) -> CompilationResult:
        tx_id = f"tx_gc_buy_{uuid.uuid4().hex[:8]}"
        debit_cash = event.amount - event.processing_fee
        
        entries = [
            LedgerEntry(account=OLPEngine._get_account_path(event, "Cash"), type="debit", amount=debit_cash),
            LedgerEntry(account=OLPEngine._get_account_path(event, "Gift Card Liability"), type="credit", amount=event.amount)
        ]
        if event.processing_fee > 0:
            entries.append(LedgerEntry(account=OLPEngine._get_account_path(event, "Payment Processing Expense"), type="debit", amount=event.processing_fee))

        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            description=f"OLP Gift Card Purchased: {event.description}",
            status="posted",
            entries=entries
        )
        return CompilationResult(initial_transaction=tx)

    @staticmethod
    def _compile_gift_card_redeemed(event: OLPEvent) -> CompilationResult:
        tx_id = f"tx_gc_red_{uuid.uuid4().hex[:8]}"
        entries = [
            LedgerEntry(account=OLPEngine._get_account_path(event, "Gift Card Liability"), type="debit", amount=event.amount),
            LedgerEntry(account=OLPEngine._get_account_path(event, "Gross Revenue"), type="credit", amount=event.amount)
        ]
        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            description=f"OLP Gift Card Redeemed: {event.description}",
            status="posted",
            entries=entries
        )
        return CompilationResult(initial_transaction=tx)

    @staticmethod
    def _compile_gift_card_breakage(event: OLPEvent) -> CompilationResult:
        tx_id = f"tx_gc_brk_{uuid.uuid4().hex[:8]}"
        entries = [
            LedgerEntry(account=OLPEngine._get_account_path(event, "Gift Card Liability"), type="debit", amount=event.amount),
            LedgerEntry(account=OLPEngine._get_account_path(event, "Gift Card Breakage"), type="credit", amount=event.amount)
        ]
        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            description=f"OLP Gift Card Breakage Recognized: {event.description}",
            status="posted",
            entries=entries
        )
        return CompilationResult(initial_transaction=tx)

    @staticmethod
    def _compile_order_placed(event: OLPEvent) -> CompilationResult:
        tx_id = f"tx_ord_{uuid.uuid4().hex[:8]}"
        base_amount = event.amount - event.tax_amount
        tax_acct = OLPEngine._get_tax_account(event)
        
        entries = [
            LedgerEntry(account=OLPEngine._get_account_path(event, "Order Clearing"), type="debit", amount=event.amount),
            LedgerEntry(account=OLPEngine._get_account_path(event, "Gross Revenue"), type="credit", amount=base_amount),
            LedgerEntry(account=tax_acct, type="credit", amount=event.tax_amount)
        ]
        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            status="posted",
            description=f"OLP Order Placed (Decoupled): {event.description}",
            entries=entries
        )
        return CompilationResult(initial_transaction=tx)

    @staticmethod
    def _compile_charge_settled(event: OLPEvent) -> CompilationResult:
        tx_id = f"tx_chg_{uuid.uuid4().hex[:8]}"
        net_amount = event.amount - event.processing_fee
        
        entries = [
            LedgerEntry(account=OLPEngine._get_account_path(event, "Payment Clearing"), type="debit", amount=net_amount),
            LedgerEntry(account=OLPEngine._get_account_path(event, "Payment Processing Expense"), type="debit", amount=event.processing_fee),
            LedgerEntry(account=OLPEngine._get_account_path(event, "Order Clearing"), type="credit", amount=event.amount)
        ]
        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            status="posted",
            description=f"OLP Gateway Charge Settled (Decoupled): {event.description}",
            entries=entries
        )
        return CompilationResult(initial_transaction=tx)

    @staticmethod
    def _compile_payout_cleared(event: OLPEvent) -> CompilationResult:
        tx_id = f"tx_pay_{uuid.uuid4().hex[:8]}"
        entries = [
            LedgerEntry(account=OLPEngine._get_account_path(event, "Cash"), type="debit", amount=event.amount),
            LedgerEntry(account=OLPEngine._get_account_path(event, "Payment Clearing"), type="credit", amount=event.amount)
        ]
        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            status="posted",
            description=f"OLP Bank Payout Cleared (Decoupled): {event.description}",
            entries=entries
        )
        return CompilationResult(initial_transaction=tx)

    @staticmethod
    def _compile_payment_settled(event: OLPEvent) -> CompilationResult:
        tx_id = f"tx_settled_{uuid.uuid4().hex[:8]}"
        
        target_amount = event.functional_amount if event.functional_amount is not None else event.amount
        fx_diff = target_amount - event.amount
        debit_cash = target_amount - event.processing_fee
        
        entries = [
            LedgerEntry(account=OLPEngine._get_account_path(event, "Cash"), type="debit", amount=debit_cash),
            LedgerEntry(account=OLPEngine._get_account_path(event, "Accounts Receivable"), type="credit", amount=event.amount)
        ]
        
        if event.processing_fee > 0:
            entries.append(LedgerEntry(account=OLPEngine._get_account_path(event, "Payment Processing Expense"), type="debit", amount=event.processing_fee))
            
        if fx_diff > 0:
            entries.append(LedgerEntry(account=OLPEngine._get_account_path(event, "Gain on FX"), type="credit", amount=fx_diff))
        elif fx_diff < 0:
            entries.append(LedgerEntry(account=OLPEngine._get_account_path(event, "Loss on FX"), type="debit", amount=abs(fx_diff)))
            
        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            status="posted",
            description=f"OLP Cash Settlement & Revaluation: {event.description}",
            entries=entries
        )
        return CompilationResult(initial_transaction=tx)

    @staticmethod
    def _compile_refund_issued(event: OLPEvent) -> CompilationResult:
        tx_id = f"tx_refund_{uuid.uuid4().hex[:8]}"
        base_refund = event.amount - event.tax_amount
        credit_account = "Accounts Receivable" if event.accounting_context.payment_method == "invoice" else "Cash"
        tax_acct = OLPEngine._get_tax_account(event)
        
        entries = [
            LedgerEntry(account=OLPEngine._get_account_path(event, "Refunds & Allowances"), type="debit", amount=base_refund),
            LedgerEntry(account=OLPEngine._get_account_path(event, credit_account), type="credit", amount=event.amount)
        ]
        
        if event.tax_amount > 0:
            entries.append(LedgerEntry(account=tax_acct, type="debit", amount=event.tax_amount))
            
        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            status="posted",
            description=f"OLP Customer Refund Issued: {event.description}",
            entries=entries
        )
        return CompilationResult(initial_transaction=tx)

    @staticmethod
    def _compile_goods_returned(event: OLPEvent, total_cogs: float) -> CompilationResult:
        tx_id = f"tx_return_{uuid.uuid4().hex[:8]}"
        entries = [
            LedgerEntry(account=OLPEngine._get_account_path(event, "Inventory"), type="debit", amount=total_cogs),
            LedgerEntry(account=OLPEngine._get_account_path(event, "Cost of Goods Sold"), type="credit", amount=total_cogs)
        ]
        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            status="posted",
            description=f"OLP Inventory Return: {event.description}",
            entries=entries
        )
        return CompilationResult(initial_transaction=tx)

    @staticmethod
    def _compile_contract_billed(event: OLPEvent) -> CompilationResult:
        tx_id = f"tx_billed_{uuid.uuid4().hex[:8]}"
        entries = [
            LedgerEntry(account=OLPEngine._get_account_path(event, "Accounts Receivable"), type="debit", amount=event.amount),
            LedgerEntry(account=OLPEngine._get_account_path(event, "Contract Assets"), type="credit", amount=event.amount)
        ]
        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            status="posted",
            description=f"OLP Contract Billed to AR: {event.description}",
            entries=entries
        )
        return CompilationResult(initial_transaction=tx)

    @staticmethod
    def _compile_invoice_written_off(event: OLPEvent) -> CompilationResult:
        tx_id = f"tx_writeoff_{uuid.uuid4().hex[:8]}"
        entries = [
            LedgerEntry(account=OLPEngine._get_account_path(event, "Bad Debt Expense"), type="debit", amount=event.amount),
            LedgerEntry(account=OLPEngine._get_account_path(event, "Accounts Receivable"), type="credit", amount=event.amount)
        ]
        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            status="posted",
            description=f"OLP Bad Debt Invoice Write-off: {event.description}",
            entries=entries
        )
        return CompilationResult(initial_transaction=tx)

    @staticmethod
    def _compile_principal_pit(event: OLPEvent, total_cogs: float) -> CompilationResult:
        """
        Rule A: Principal + Physical/Digital + Point-in-Time (In Cents)
        """
        tx_id = f"tx_pit_{uuid.uuid4().hex[:8]}"
        ctx = event.accounting_context
        
        debit_account = OLPEngine._get_debit_asset_account(event)
        base_amount = event.amount - event.tax_amount
        tax_acct = OLPEngine._get_tax_account(event)
        
        if event.event_type == "payment_received":
            debit_cash = event.amount - event.processing_fee if debit_account == OLPEngine._get_account_path(event, "Cash") else event.amount
            entries = [
                LedgerEntry(account=debit_account, type="debit", amount=debit_cash),
                LedgerEntry(account=OLPEngine._get_account_path(event, "Deferred Revenue"), type="credit", amount=base_amount),
                LedgerEntry(account=tax_acct, type="credit", amount=event.tax_amount)
            ]
            if event.processing_fee > 0 and debit_account == OLPEngine._get_account_path(event, "Cash"):
                entries.append(LedgerEntry(account=OLPEngine._get_account_path(event, "Payment Processing Expense"), type="debit", amount=event.processing_fee))
            desc = f"OLP Principal Payment Received (Deferred): {event.description}"
            
        elif event.event_type == "fulfillment_completed":
            entries = [
                LedgerEntry(account=OLPEngine._get_account_path(event, "Deferred Revenue"), type="debit", amount=base_amount),
                LedgerEntry(account=OLPEngine._get_account_path(event, "Gross Revenue"), type="credit", amount=base_amount)
            ]
            if total_cogs > 0:
                entries.append(LedgerEntry(account=OLPEngine._get_account_path(event, "Cost of Goods Sold"), type="debit", amount=total_cogs))
                entries.append(LedgerEntry(account=OLPEngine._get_account_path(event, "Inventory"), type="credit", amount=total_cogs))
            desc = f"OLP Principal Delivery / Fulfillment (Revenue Recognized): {event.description}"
            
        else: # immediate_sale
            debit_cash = event.amount - event.processing_fee if debit_account == OLPEngine._get_account_path(event, "Cash") else event.amount
            
            # Apply Sales Returns Reserve split if expected returns rate > 0
            if event.expected_return_rate_basis_points > 0:
                refund_reserve = (base_amount * event.expected_return_rate_basis_points) // 10000
                net_revenue = base_amount - refund_reserve
                
                entries = [
                    LedgerEntry(account=debit_account, type="debit", amount=debit_cash),
                    LedgerEntry(account=OLPEngine._get_account_path(event, "Gross Revenue"), type="credit", amount=net_revenue),
                    LedgerEntry(account=OLPEngine._get_account_path(event, "Refund Reserve"), type="credit", amount=refund_reserve),
                    LedgerEntry(account=tax_acct, type="credit", amount=event.tax_amount)
                ]
            else:
                entries = [
                    LedgerEntry(account=debit_account, type="debit", amount=debit_cash),
                    LedgerEntry(account=OLPEngine._get_account_path(event, "Gross Revenue"), type="credit", amount=base_amount),
                    LedgerEntry(account=tax_acct, type="credit", amount=event.tax_amount)
                ]
                
            if event.processing_fee > 0 and debit_account == OLPEngine._get_account_path(event, "Cash"):
                entries.append(LedgerEntry(account=OLPEngine._get_account_path(event, "Payment Processing Expense"), type="debit", amount=event.processing_fee))
            
            if total_cogs > 0:
                if event.expected_return_rate_basis_points > 0:
                    recoverable_cost = (total_cogs * event.expected_return_rate_basis_points) // 10000
                    net_cogs = total_cogs - recoverable_cost
                    entries.append(LedgerEntry(account=OLPEngine._get_account_path(event, "Cost of Goods Sold"), type="debit", amount=net_cogs))
                    entries.append(LedgerEntry(account=OLPEngine._get_account_path(event, "Right to Recover"), type="debit", amount=recoverable_cost))
                else:
                    entries.append(LedgerEntry(account=OLPEngine._get_account_path(event, "Cost of Goods Sold"), type="debit", amount=total_cogs))
                entries.append(LedgerEntry(account=OLPEngine._get_account_path(event, "Inventory"), type="credit", amount=total_cogs))
                
            desc = f"OLP Principal Immediate Sale booking for: {event.description}"

        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            description=desc,
            status="posted",
            entries=entries
        )
        return CompilationResult(initial_transaction=tx)

    @staticmethod
    def _compile_principal_ot(event: OLPEvent) -> CompilationResult:
        """
        Rule B: Principal + Digital/SaaS + Over-Time (In Cents)
        """
        ctx = event.accounting_context
        term = ctx.term_months
        debit_account = OLPEngine._get_debit_asset_account(event)
        base_amount = event.amount - event.tax_amount
        debit_cash = event.amount - event.processing_fee if debit_account == OLPEngine._get_account_path(event, "Cash") else event.amount
        tax_acct = OLPEngine._get_tax_account(event)
        
        # Initial booking transaction
        init_tx_id = f"tx_init_{uuid.uuid4().hex[:8]}"
        init_entries = [
            LedgerEntry(account=debit_account, type="debit", amount=debit_cash),
            LedgerEntry(account=OLPEngine._get_account_path(event, "Deferred Revenue"), type="credit", amount=base_amount),
            LedgerEntry(account=tax_acct, type="credit", amount=event.tax_amount)
        ]
        if event.processing_fee > 0 and debit_account == OLPEngine._get_account_path(event, "Cash"):
            init_entries.append(LedgerEntry(account=OLPEngine._get_account_path(event, "Payment Processing Expense"), type="debit", amount=event.processing_fee))
            
        # Add Capitalized Commissions
        if event.capitalized_costs > 0:
            init_entries.append(LedgerEntry(account=OLPEngine._get_account_path(event, "Deferred Contract Costs"), type="debit", amount=event.capitalized_costs))
            init_entries.append(LedgerEntry(account=OLPEngine._get_account_path(event, "Commissions Payable"), type="credit", amount=event.capitalized_costs))

        init_tx = Transaction(
            transaction_id=init_tx_id,
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            description=f"OLP Principal Initial Over-Time booking for: {event.description}",
            status="posted",
            entries=init_entries
        )

        # Generate amortization schedules
        amort_txs = []
        monthly_amt = base_amount // term
        monthly_cost = event.capitalized_costs // term if event.capitalized_costs > 0 else 0
        
        accum_rev = 0
        accum_cost = 0

        event_date = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
        
        for i in range(1, term + 1):
            if i == term:
                current_monthly_rev = base_amount - accum_rev
                current_monthly_cost = event.capitalized_costs - accum_cost
            else:
                current_monthly_rev = monthly_amt
                current_monthly_cost = monthly_cost
                accum_rev += current_monthly_rev
                accum_cost += current_monthly_cost

            year = event_date.year + (event_date.month - 1 + i) // 12
            month = (event_date.month - 1 + i) % 12 + 1
            day = min(event_date.day, 28)
            amort_date = date(year, month, day).isoformat() + "T00:00:00Z"

            amort_tx_id = f"tx_amort_{i}_{uuid.uuid4().hex[:8]}"
            amort_entries = [
                LedgerEntry(account=OLPEngine._get_account_path(event, "Deferred Revenue"), type="debit", amount=current_monthly_rev),
                LedgerEntry(account=OLPEngine._get_account_path(event, "Subscription Revenue"), type="credit", amount=current_monthly_rev)
            ]
            
            if event.capitalized_costs > 0:
                amort_entries.append(LedgerEntry(account=OLPEngine._get_account_path(event, "Amortized Commission Expense"), type="debit", amount=current_monthly_cost))
                amort_entries.append(LedgerEntry(account=OLPEngine._get_account_path(event, "Deferred Contract Costs"), type="credit", amount=current_monthly_cost))

            amort_tx = Transaction(
                transaction_id=amort_tx_id,
                source_event_id=event.event_id,
                idempotency_key=event.idempotency_key,
                date=amort_date,
                description=f"OLP Amortization Month {i}/{term} for: {event.description}",
                status="posted",
                entries=amort_entries
            )
            amort_txs.append(amort_tx)

        return CompilationResult(initial_transaction=init_tx, amortization_schedule=amort_txs)

    @staticmethod
    def _compile_agent_pit(event: OLPEvent) -> CompilationResult:
        """
        Rule C: Agent + Physical/Digital + Point-in-Time (In Cents)
        """
        ctx = event.accounting_context
        debit_account = OLPEngine._get_debit_asset_account(event)
        debit_cash = event.amount - event.processing_fee if debit_account == OLPEngine._get_account_path(event, "Cash") else event.amount
        
        base_amount = event.amount - event.tax_amount
        commission = int(base_amount * ctx.platform_fee_percent)
        vendor_cut = base_amount - commission
        tax_acct = OLPEngine._get_tax_account(event)

        tx_id = f"tx_agent_pit_{uuid.uuid4().hex[:8]}"
        
        if event.event_type == "payment_received":
            entries = [
                LedgerEntry(account=debit_account, type="debit", amount=debit_cash),
                LedgerEntry(account=OLPEngine._get_account_path(event, "Deferred Payable (Vendor)"), type="credit", amount=vendor_cut),
                LedgerEntry(account=OLPEngine._get_account_path(event, "Deferred Commission Revenue"), type="credit", amount=commission),
                LedgerEntry(account=tax_acct, type="credit", amount=event.tax_amount)
            ]
            if event.processing_fee > 0 and debit_account == OLPEngine._get_account_path(event, "Cash"):
                entries.append(LedgerEntry(account=OLPEngine._get_account_path(event, "Payment Processing Expense"), type="debit", amount=event.processing_fee))
            desc = f"OLP Agent Payment Received (Deferred): {event.description}"
            
        elif event.event_type == "fulfillment_completed":
            entries = [
                LedgerEntry(account=OLPEngine._get_account_path(event, "Deferred Payable (Vendor)"), type="debit", amount=vendor_cut),
                LedgerEntry(account=OLPEngine._get_account_path(event, "Accounts Payable (Vendor)"), type="credit", amount=vendor_cut),
                LedgerEntry(account=OLPEngine._get_account_path(event, "Deferred Commission Revenue"), type="debit", amount=commission),
                LedgerEntry(account=OLPEngine._get_account_path(event, "Commission Revenue"), type="credit", amount=commission)
            ]
            desc = f"OLP Agent Fulfillment (Revenue & Payable Recognized): {event.description}"
            
        else: # immediate_sale
            entries = [
                LedgerEntry(account=debit_account, type="debit", amount=debit_cash),
                LedgerEntry(account=OLPEngine._get_account_path(event, "Accounts Payable (Vendor)"), type="credit", amount=vendor_cut),
                LedgerEntry(account=OLPEngine._get_account_path(event, "Commission Revenue"), type="credit", amount=commission),
                LedgerEntry(account=tax_acct, type="credit", amount=event.tax_amount)
            ]
            if event.processing_fee > 0 and debit_account == OLPEngine._get_account_path(event, "Cash"):
                entries.append(LedgerEntry(account=OLPEngine._get_account_path(event, "Payment Processing Expense"), type="debit", amount=event.processing_fee))
            desc = f"OLP Agent Immediate Sale booking for: {event.description}"
        
        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            description=desc,
            entries=entries
        )
        return CompilationResult(initial_transaction=tx)

    @staticmethod
    def _compile_agent_ot(event: OLPEvent) -> CompilationResult:
        """
        Rule D: Agent + Digital/SaaS + Over-Time (In Cents)
        """
        ctx = event.accounting_context
        term = ctx.term_months
        debit_account = OLPEngine._get_debit_asset_account(event)
        debit_cash = event.amount - event.processing_fee if debit_account == OLPEngine._get_account_path(event, "Cash") else event.amount
        
        base_amount = event.amount - event.tax_amount
        commission = int(base_amount * ctx.platform_fee_percent)
        vendor_cut = base_amount - commission
        tax_acct = OLPEngine._get_tax_account(event)

        # Initial booking transaction
        init_tx_id = f"tx_agent_init_{uuid.uuid4().hex[:8]}"
        init_entries = [
            LedgerEntry(account=debit_account, type="debit", amount=debit_cash),
            LedgerEntry(account=OLPEngine._get_account_path(event, "Deferred Payable (Vendor)"), type="credit", amount=vendor_cut),
            LedgerEntry(account=OLPEngine._get_account_path(event, "Deferred Commission Revenue"), type="credit", amount=commission),
            LedgerEntry(account=tax_acct, type="credit", amount=event.tax_amount)
        ]
        if event.processing_fee > 0 and debit_account == OLPEngine._get_account_path(event, "Cash"):
            init_entries.append(LedgerEntry(account=OLPEngine._get_account_path(event, "Payment Processing Expense"), type="debit", amount=event.processing_fee))
            
        init_tx = Transaction(
            transaction_id=init_tx_id,
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            description=f"OLP Agent Initial Over-Time booking for: {event.description}",
            status="posted",
            entries=init_entries
        )

        # Generate amortization schedules
        amort_txs = []
        monthly_commission = commission // term
        monthly_vendor = vendor_cut // term
        
        accum_comm = 0
        accum_vendor = 0

        event_date = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
        
        for i in range(1, term + 1):
            if i == term:
                curr_comm = commission - accum_comm
                curr_vendor = vendor_cut - accum_vendor
            else:
                curr_comm = monthly_commission
                curr_vendor = monthly_vendor
                accum_comm += curr_comm
                accum_vendor += curr_vendor

            year = event_date.year + (event_date.month - 1 + i) // 12
            month = (event_date.month - 1 + i) % 12 + 1
            day = min(event_date.day, 28)
            amort_date = date(year, month, day).isoformat() + "T00:00:00Z"

            amort_tx_id = f"tx_agent_amort_{i}_{uuid.uuid4().hex[:8]}"
            amort_entries = [
                LedgerEntry(account=OLPEngine._get_account_path(event, "Deferred Payable (Vendor)"), type="debit", amount=curr_vendor),
                LedgerEntry(account=OLPEngine._get_account_path(event, "Accounts Payable (Vendor)"), type="credit", amount=curr_vendor),
                LedgerEntry(account=OLPEngine._get_account_path(event, "Deferred Commission Revenue"), type="debit", amount=curr_comm),
                LedgerEntry(account=OLPEngine._get_account_path(event, "Commission Revenue"), type="credit", amount=curr_comm)
            ]
            
            amort_tx = Transaction(
                transaction_id=amort_tx_id,
                source_event_id=event.event_id,
                idempotency_key=event.idempotency_key,
                date=amort_date,
                description=f"OLP Agent Amortization Month {i}/{term} for: {event.description}",
                entries=amort_entries
            )
            amort_txs.append(amort_tx)

        return CompilationResult(initial_transaction=init_tx, amortization_schedule=amort_txs)

    @staticmethod
    def _compile_revenue_adjustment(event: OLPEvent) -> CompilationResult:
        tx_id = f"tx_rev_adj_{uuid.uuid4().hex[:8]}"
        credit_account = OLPEngine._get_debit_asset_account(event)
        
        entries = [
            LedgerEntry(account=OLPEngine._get_account_path(event, "Refunds & Allowances"), type="debit", amount=event.amount),
            LedgerEntry(account=credit_account, type="credit", amount=event.amount)
        ]
        
        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            description=f"OLP Revenue Adjustment Posted: {event.description}",
            status="posted",
            entries=entries
        )
        return CompilationResult(initial_transaction=tx)

    @staticmethod
    def _compile_invoice_voided(event: OLPEvent) -> CompilationResult:
        tx_id = f"tx_void_{uuid.uuid4().hex[:8]}"
        base_amount = event.amount - event.tax_amount
        tax_acct = OLPEngine._get_tax_account(event)
        
        entries = [
            LedgerEntry(account=OLPEngine._get_account_path(event, "Gross Revenue"), type="debit", amount=base_amount),
            LedgerEntry(account=OLPEngine._get_account_path(event, "Accounts Receivable"), type="credit", amount=event.amount)
        ]
        if event.tax_amount > 0:
            entries.append(LedgerEntry(account=tax_acct, type="debit", amount=event.tax_amount))
            
        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            description=f"OLP Invoice Voided: {event.description}",
            status="posted",
            entries=entries
        )
        return CompilationResult(initial_transaction=tx)

    @staticmethod
    def _compile_accrual_reversed(event: OLPEvent) -> CompilationResult:
        tx_id = f"tx_accrual_rev_{uuid.uuid4().hex[:8]}"
        
        entries = [
            LedgerEntry(account=OLPEngine._get_account_path(event, "Accounts Payable (Vendor)"), type="debit", amount=event.amount),
            LedgerEntry(account=OLPEngine._get_account_path(event, "Gross Revenue"), type="credit", amount=event.amount)
        ]
        
        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            description=f"OLP Accrual Reversed: {event.description}",
            status="posted",
            entries=entries
        )
        return CompilationResult(initial_transaction=tx)
