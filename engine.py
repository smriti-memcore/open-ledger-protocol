import uuid
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Optional

@dataclass
class AccountingContext:
    role: str                       # "principal" | "agent"
    product_type: str               # "physical" | "digital_saas" | "digital_download"
    recognition: str                # "point_in_time" | "over_time"
    term_months: Optional[int] = None
    platform_fee_percent: float = 0.20  # Only used if role is "agent"
    payment_method: str = "card"    # "card" | "invoice"

@dataclass
class LineItem:
    item_id: str
    price: float
    cogs_estimate: float = 0.0

@dataclass
class OLPEvent:
    event_id: str
    timestamp: str
    amount: float
    currency: str
    description: str
    customer_id: str
    accounting_context: AccountingContext
    event_type: str = "immediate_sale"
    tax_amount: float = 0.0
    processing_fee: float = 0.0
    discount_amount: float = 0.0
    line_items: List[LineItem] = field(default_factory=list)

@dataclass
class LedgerEntry:
    account: str
    type: str  # "debit" | "credit"
    amount: float

@dataclass
class Transaction:
    transaction_id: str
    source_event_id: str
    date: str
    description: str
    entries: List[LedgerEntry] = field(default_factory=list)

    def is_balanced(self) -> bool:
        debits = sum(e.amount for e in self.entries if e.type == "debit")
        credits = sum(e.amount for e in self.entries if e.type == "credit")
        return abs(debits - credits) < 1e-6

@dataclass
class CompilationResult:
    initial_transaction: Transaction
    amortization_schedule: List[Transaction] = field(default_factory=list)

class OLPEngine:
    @staticmethod
    def _allocate_discounts(event: OLPEvent) -> OLPEvent:
        """
        Applies proportional discount allocation (ASC 606 Step 3).
        Redistributes event.discount_amount across line items based on relative pricing weight.
        """
        if event.discount_amount <= 0.0 or not event.line_items:
            return event
            
        total_price = sum(item.price for item in event.line_items)
        if total_price <= 0.0:
            return event

        new_items = []
        accum_discount = 0.0
        n_items = len(event.line_items)

        for idx, item in enumerate(event.line_items):
            if idx == n_items - 1:
                current_discount = round(event.discount_amount - accum_discount, 2)
            else:
                current_discount = round(event.discount_amount * (item.price / total_price), 2)
                accum_discount += current_discount

            new_price = max(0.0, round(item.price - current_discount, 2))
            new_items.append(LineItem(
                item_id=item.item_id,
                price=new_price,
                cogs_estimate=item.cogs_estimate
            ))
            
        event.line_items = new_items
        return event

    @staticmethod
    def compile_event(event: OLPEvent) -> CompilationResult:
        # 1. Pre-process discounts
        event = OLPEngine._allocate_discounts(event)
        
        ctx = event.accounting_context
        
        # Validation checks
        if ctx.recognition == "over_time" and (ctx.term_months is None or ctx.term_months < 1):
            raise ValueError("term_months must be >= 1 for over_time recognition")
        
        if ctx.role not in ("principal", "agent"):
            raise ValueError(f"Unknown role: {ctx.role}")
            
        if ctx.product_type not in ("physical", "digital_saas", "digital_download"):
            raise ValueError(f"Unknown product_type: {ctx.product_type}")

        if ctx.recognition not in ("point_in_time", "over_time"):
            raise ValueError(f"Unknown recognition timing: {ctx.recognition}")

        # Compute total COGS
        total_cogs = sum(item.cogs_estimate for item in event.line_items)

        # Route lifecycle adjustment events (Payment Settlement, Refunds, Returns)
        if event.event_type == "payment_settled":
            return OLPEngine._compile_payment_settled(event)
        elif event.event_type == "refund_issued":
            return OLPEngine._compile_refund_issued(event)
        elif event.event_type == "goods_returned":
            return OLPEngine._compile_goods_returned(event, total_cogs)

        # Route matching rules
        if ctx.role == "principal":
            if ctx.recognition == "point_in_time":
                return OLPEngine._compile_principal_pit(event, total_cogs)
            else:
                return OLPEngine._compile_principal_ot(event)
        else: # agent
            if ctx.recognition == "point_in_time":
                return OLPEngine._compile_agent_pit(event)
            else:
                return OLPEngine._compile_agent_ot(event)

    @staticmethod
    def _compile_payment_settled(event: OLPEvent) -> CompilationResult:
        """
        Record cash settlement for an Accounts Receivable invoice.
        """
        tx_id = f"tx_settled_{uuid.uuid4().hex[:8]}"
        debit_cash = round(event.amount - event.processing_fee, 2)
        
        entries = [
            LedgerEntry(account="Cash", type="debit", amount=debit_cash),
            LedgerEntry(account="Accounts Receivable", type="credit", amount=event.amount)
        ]
        
        if event.processing_fee > 0.0:
            entries.append(LedgerEntry(account="Payment Processing Expense", type="debit", amount=event.processing_fee))
            
        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            date=event.timestamp,
            description=f"OLP Cash Settlement for Invoice: {event.description}",
            entries=entries
        )
        return CompilationResult(initial_transaction=tx)

    @staticmethod
    def _compile_refund_issued(event: OLPEvent) -> CompilationResult:
        """
        Record customer refund using a contra-revenue account.
        """
        tx_id = f"tx_refund_{uuid.uuid4().hex[:8]}"
        base_refund = round(event.amount - event.tax_amount, 2)
        credit_account = "Accounts Receivable" if event.accounting_context.payment_method == "invoice" else "Cash"
        
        entries = [
            LedgerEntry(account="Refunds & Allowances", type="debit", amount=base_refund),
            LedgerEntry(account=credit_account, type="credit", amount=event.amount)
        ]
        
        if event.tax_amount > 0.0:
            entries.append(LedgerEntry(account="Sales Tax Payable", type="debit", amount=event.tax_amount))
            
        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            date=event.timestamp,
            description=f"OLP Customer Refund Issued: {event.description}",
            entries=entries
        )
        return CompilationResult(initial_transaction=tx)

    @staticmethod
    def _compile_goods_returned(event: OLPEvent, total_cogs: float) -> CompilationResult:
        """
        Reverse Cost of Goods Sold and write physical inventory back.
        """
        tx_id = f"tx_return_{uuid.uuid4().hex[:8]}"
        entries = [
            LedgerEntry(account="Inventory", type="debit", amount=total_cogs),
            LedgerEntry(account="Cost of Goods Sold", type="credit", amount=total_cogs)
        ]
        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            date=event.timestamp,
            description=f"OLP Inventory Return: {event.description}",
            entries=entries
        )
        return CompilationResult(initial_transaction=tx)

    @staticmethod
    def _compile_principal_pit(event: OLPEvent, total_cogs: float) -> CompilationResult:
        """
        Rule A: Principal + Physical/Digital + Point-in-Time
        Recognize gross revenue immediately or deferred based on delivery status.
        """
        tx_id = f"tx_pit_{uuid.uuid4().hex[:8]}"
        ctx = event.accounting_context
        
        debit_asset = "Accounts Receivable" if ctx.payment_method == "invoice" else "Cash"
        base_amount = round(event.amount - event.tax_amount, 2)
        
        if event.event_type == "payment_received":
            # Phase 1: Payment received but not yet fulfilled
            debit_cash = round(event.amount - event.processing_fee, 2) if debit_asset == "Cash" else event.amount
            entries = [
                LedgerEntry(account=debit_asset, type="debit", amount=debit_cash),
                LedgerEntry(account="Deferred Revenue", type="credit", amount=base_amount),
                LedgerEntry(account="Sales Tax Payable", type="credit", amount=event.tax_amount)
            ]
            if event.processing_fee > 0.0 and debit_asset == "Cash":
                entries.append(LedgerEntry(account="Payment Processing Expense", type="debit", amount=event.processing_fee))
            desc = f"OLP Principal Payment Received (Deferred): {event.description}"
            
        elif event.event_type == "fulfillment_completed":
            # Phase 2: Shipment/Delivery completed (Control Transfers)
            entries = [
                LedgerEntry(account="Deferred Revenue", type="debit", amount=base_amount),
                LedgerEntry(account="Gross Revenue", type="credit", amount=base_amount)
            ]
            if total_cogs > 0:
                entries.append(LedgerEntry(account="Cost of Goods Sold", type="debit", amount=total_cogs))
                entries.append(LedgerEntry(account="Inventory", type="credit", amount=total_cogs))
            desc = f"OLP Principal Delivery / Fulfillment (Revenue Recognized): {event.description}"
            
        else: # immediate_sale
            debit_cash = round(event.amount - event.processing_fee, 2) if debit_asset == "Cash" else event.amount
            entries = [
                LedgerEntry(account=debit_asset, type="debit", amount=debit_cash),
                LedgerEntry(account="Gross Revenue", type="credit", amount=base_amount),
                LedgerEntry(account="Sales Tax Payable", type="credit", amount=event.tax_amount)
            ]
            if event.processing_fee > 0.0 and debit_asset == "Cash":
                entries.append(LedgerEntry(account="Payment Processing Expense", type="debit", amount=event.processing_fee))
            if total_cogs > 0:
                entries.append(LedgerEntry(account="Cost of Goods Sold", type="debit", amount=total_cogs))
                entries.append(LedgerEntry(account="Inventory", type="credit", amount=total_cogs))
            desc = f"OLP Principal Immediate Sale booking for: {event.description}"

        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            date=event.timestamp,
            description=desc,
            entries=entries
        )
        return CompilationResult(initial_transaction=tx)

    @staticmethod
    def _compile_principal_ot(event: OLPEvent) -> CompilationResult:
        """
        Rule B: Principal + Digital/SaaS + Over-Time
        Recognize deferred revenue and amortize it.
        """
        ctx = event.accounting_context
        term = ctx.term_months
        debit_asset = "Accounts Receivable" if ctx.payment_method == "invoice" else "Cash"
        base_amount = round(event.amount - event.tax_amount, 2)
        debit_cash = round(event.amount - event.processing_fee, 2) if debit_asset == "Cash" else event.amount
        
        # Initial booking transaction
        init_tx_id = f"tx_init_{uuid.uuid4().hex[:8]}"
        init_entries = [
            LedgerEntry(account=debit_asset, type="debit", amount=debit_cash),
            LedgerEntry(account="Deferred Revenue", type="credit", amount=base_amount),
            LedgerEntry(account="Sales Tax Payable", type="credit", amount=event.tax_amount)
        ]
        if event.processing_fee > 0.0 and debit_asset == "Cash":
            init_entries.append(LedgerEntry(account="Payment Processing Expense", type="debit", amount=event.processing_fee))
            
        init_tx = Transaction(
            transaction_id=init_tx_id,
            source_event_id=event.event_id,
            date=event.timestamp,
            description=f"OLP Principal Initial Over-Time booking for: {event.description}",
            entries=init_entries
        )

        # Generate amortization schedules
        amort_txs = []
        monthly_amt = round(base_amount / term, 2)
        accumulated = 0.0

        event_date = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
        
        for i in range(1, term + 1):
            if i == term:
                current_monthly_amt = round(base_amount - accumulated, 2)
            else:
                current_monthly_amt = monthly_amt
                accumulated += current_monthly_amt

            year = event_date.year + (event_date.month - 1 + i) // 12
            month = (event_date.month - 1 + i) % 12 + 1
            day = min(event_date.day, 28)
            amort_date = date(year, month, day).isoformat() + "T00:00:00Z"

            amort_tx_id = f"tx_amort_{i}_{uuid.uuid4().hex[:8]}"
            amort_entries = [
                LedgerEntry(account="Deferred Revenue", type="debit", amount=current_monthly_amt),
                LedgerEntry(account="Subscription Revenue", type="credit", amount=current_monthly_amt)
            ]
            
            amort_tx = Transaction(
                transaction_id=amort_tx_id,
                source_event_id=event.event_id,
                date=amort_date,
                description=f"OLP Amortization Month {i}/{term} for: {event.description}",
                entries=amort_entries
            )
            amort_txs.append(amort_tx)

        return CompilationResult(initial_transaction=init_tx, amortization_schedule=amort_txs)

    @staticmethod
    def _compile_agent_pit(event: OLPEvent) -> CompilationResult:
        """
        Rule C: Agent + Physical/Digital + Point-in-Time
        Recognize net commission immediately or defer pending delivery.
        """
        ctx = event.accounting_context
        debit_asset = "Accounts Receivable" if ctx.payment_method == "invoice" else "Cash"
        debit_cash = round(event.amount - event.processing_fee, 2) if debit_asset == "Cash" else event.amount
        
        base_amount = round(event.amount - event.tax_amount, 2)
        commission = round(base_amount * ctx.platform_fee_percent, 2)
        vendor_cut = round(base_amount - commission, 2)

        tx_id = f"tx_agent_pit_{uuid.uuid4().hex[:8]}"
        
        if event.event_type == "payment_received":
            # Phase 1: Payment received but not yet delivered
            entries = [
                LedgerEntry(account=debit_asset, type="debit", amount=debit_cash),
                LedgerEntry(account="Deferred Payable (Vendor)", type="credit", amount=vendor_cut),
                LedgerEntry(account="Deferred Commission Revenue", type="credit", amount=commission),
                LedgerEntry(account="Sales Tax Payable", type="credit", amount=event.tax_amount)
            ]
            if event.processing_fee > 0.0 and debit_asset == "Cash":
                entries.append(LedgerEntry(account="Payment Processing Expense", type="debit", amount=event.processing_fee))
            desc = f"OLP Agent Payment Received (Deferred): {event.description}"
            
        elif event.event_type == "fulfillment_completed":
            # Phase 2: Delivery completed (Vendor Payable & Commission Earned)
            entries = [
                LedgerEntry(account="Deferred Payable (Vendor)", type="debit", amount=vendor_cut),
                LedgerEntry(account="Accounts Payable (Vendor)", type="credit", amount=vendor_cut),
                LedgerEntry(account="Deferred Commission Revenue", type="debit", amount=commission),
                LedgerEntry(account="Commission Revenue", type="credit", amount=commission)
            ]
            desc = f"OLP Agent Fulfillment (Revenue & Payable Recognized): {event.description}"
            
        else: # immediate_sale
            entries = [
                LedgerEntry(account=debit_asset, type="debit", amount=debit_cash),
                LedgerEntry(account="Accounts Payable (Vendor)", type="credit", amount=vendor_cut),
                LedgerEntry(account="Commission Revenue", type="credit", amount=commission),
                LedgerEntry(account="Sales Tax Payable", type="credit", amount=event.tax_amount)
            ]
            if event.processing_fee > 0.0 and debit_asset == "Cash":
                entries.append(LedgerEntry(account="Payment Processing Expense", type="debit", amount=event.processing_fee))
            desc = f"OLP Agent Immediate Sale booking for: {event.description}"
        
        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            date=event.timestamp,
            description=desc,
            entries=entries
        )
        return CompilationResult(initial_transaction=tx)

    @staticmethod
    def _compile_agent_ot(event: OLPEvent) -> CompilationResult:
        """
        Rule D: Agent + Digital/SaaS + Over-Time
        Recognize cash, deferred payable, deferred commission, and amortize.
        """
        ctx = event.accounting_context
        term = ctx.term_months
        debit_asset = "Accounts Receivable" if ctx.payment_method == "invoice" else "Cash"
        debit_cash = round(event.amount - event.processing_fee, 2) if debit_asset == "Cash" else event.amount
        
        base_amount = round(event.amount - event.tax_amount, 2)
        commission = round(base_amount * ctx.platform_fee_percent, 2)
        vendor_cut = round(base_amount - commission, 2)

        # Initial booking transaction
        init_tx_id = f"tx_agent_init_{uuid.uuid4().hex[:8]}"
        init_entries = [
            LedgerEntry(account=debit_asset, type="debit", amount=debit_cash),
            LedgerEntry(account="Deferred Payable (Vendor)", type="credit", amount=vendor_cut),
            LedgerEntry(account="Deferred Commission Revenue", type="credit", amount=commission),
            LedgerEntry(account="Sales Tax Payable", type="credit", amount=event.tax_amount)
        ]
        if event.processing_fee > 0.0 and debit_asset == "Cash":
            init_entries.append(LedgerEntry(account="Payment Processing Expense", type="debit", amount=event.processing_fee))
            
        init_tx = Transaction(
            transaction_id=init_tx_id,
            source_event_id=event.event_id,
            date=event.timestamp,
            description=f"OLP Agent Initial Over-Time booking for: {event.description}",
            entries=init_entries
        )

        # Generate amortization schedules
        amort_txs = []
        monthly_commission = round(commission / term, 2)
        monthly_vendor = round(vendor_cut / term, 2)
        
        accum_comm = 0.0
        accum_vendor = 0.0

        event_date = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
        
        for i in range(1, term + 1):
            if i == term:
                curr_comm = round(commission - accum_comm, 2)
                curr_vendor = round(vendor_cut - accum_vendor, 2)
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
                LedgerEntry(account="Deferred Payable (Vendor)", type="debit", amount=curr_vendor),
                LedgerEntry(account="Accounts Payable (Vendor)", type="credit", amount=curr_vendor),
                LedgerEntry(account="Deferred Commission Revenue", type="debit", amount=curr_comm),
                LedgerEntry(account="Commission Revenue", type="credit", amount=curr_comm)
            ]
            
            amort_tx = Transaction(
                transaction_id=amort_tx_id,
                source_event_id=event.event_id,
                date=amort_date,
                description=f"OLP Agent Amortization Month {i}/{term} for: {event.description}",
                entries=amort_entries
            )
            amort_txs.append(amort_tx)

        return CompilationResult(initial_transaction=init_tx, amortization_schedule=amort_txs)
