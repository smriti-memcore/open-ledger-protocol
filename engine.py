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
    platform_fee_percent: float = 0.20  # Keep platform cut percentage as a float multiplier (e.g., 0.20)
    payment_method: str = "card"    # "card" | "invoice"

@dataclass
class LineItem:
    item_id: str
    price: int                      # In cents (e.g. $10.00 = 1000)
    cogs_estimate: int = 0          # In cents

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
    processing_fee: int = 0         # In cents
    discount_amount: int = 0        # In cents
    line_items: List[LineItem] = field(default_factory=list)

@dataclass
class LedgerEntry:
    account: str                    # Standardized path string, e.g. "/assets/liquid/cash"
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
    entries: List[LedgerEntry] = field(default_factory=list)

    def is_balanced(self) -> bool:
        debits = sum(e.amount for e in self.entries if e.type == "debit")
        credits = sum(e.amount for e in self.entries if e.type == "credit")
        return debits == credits

@dataclass
class CompilationResult:
    initial_transaction: Transaction
    amortization_schedule: List[Transaction] = field(default_factory=list)

# Chart of Accounts standard mappings
ACCOUNT_PATHS = {
    "Cash": "/assets/liquid/cash",
    "Accounts Receivable": "/assets/receivables/ar",
    "Inventory": "/assets/inventory",
    "Deferred Revenue": "/liabilities/deferred/revenue",
    "Deferred Payable (Vendor)": "/liabilities/deferred/payable_vendor",
    "Deferred Commission Revenue": "/liabilities/deferred/commission",
    "Accounts Payable (Vendor)": "/liabilities/payables/vendor",
    "Sales Tax Payable": "/liabilities/tax/payable",
    "Gross Revenue": "/equity/revenue/gross",
    "Subscription Revenue": "/equity/revenue/subscription",
    "Commission Revenue": "/equity/revenue/commission",
    "Refunds & Allowances": "/equity/revenue/refunds_allowances",
    "Payment Processing Expense": "/expenses/processing/fees",
    "Cost of Goods Sold": "/expenses/cogs"
}

class OLPEngine:
    @staticmethod
    def _allocate_discounts(event: OLPEvent) -> OLPEvent:
        """
        Applies proportional discount allocation (ASC 606 Step 3) using Integer-cents arithmetic.
        """
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
                cogs_estimate=item.cogs_estimate
            ))
            
        event.line_items = new_items
        return event

    @staticmethod
    def compile_event(event: OLPEvent) -> CompilationResult:
        # Pre-process discount allocations
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

        # Route lifecycle events
        if event.event_type == "payment_settled":
            return OLPEngine._compile_payment_settled(event)
        elif event.event_type == "refund_issued":
            return OLPEngine._compile_refund_issued(event)
        elif event.event_type == "goods_returned":
            return OLPEngine._compile_goods_returned(event, total_cogs)

        # Route core rules
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
        Record cash settlement for an Accounts Receivable invoice (In Cents).
        """
        tx_id = f"tx_settled_{uuid.uuid4().hex[:8]}"
        debit_cash = event.amount - event.processing_fee
        
        entries = [
            LedgerEntry(account=ACCOUNT_PATHS["Cash"], type="debit", amount=debit_cash),
            LedgerEntry(account=ACCOUNT_PATHS["Accounts Receivable"], type="credit", amount=event.amount)
        ]
        
        if event.processing_fee > 0:
            entries.append(LedgerEntry(account=ACCOUNT_PATHS["Payment Processing Expense"], type="debit", amount=event.processing_fee))
            
        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            status="posted",
            description=f"OLP Cash Settlement for Invoice: {event.description}",
            entries=entries
        )
        return CompilationResult(initial_transaction=tx)

    @staticmethod
    def _compile_refund_issued(event: OLPEvent) -> CompilationResult:
        """
        Record customer refund using a contra-revenue account (In Cents).
        """
        tx_id = f"tx_refund_{uuid.uuid4().hex[:8]}"
        base_refund = event.amount - event.tax_amount
        credit_account = "Accounts Receivable" if event.accounting_context.payment_method == "invoice" else "Cash"
        
        entries = [
            LedgerEntry(account=ACCOUNT_PATHS["Refunds & Allowances"], type="debit", amount=base_refund),
            LedgerEntry(account=ACCOUNT_PATHS[credit_account], type="credit", amount=event.amount)
        ]
        
        if event.tax_amount > 0:
            entries.append(LedgerEntry(account=ACCOUNT_PATHS["Sales Tax Payable"], type="debit", amount=event.tax_amount))
            
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
        """
        Reverse Cost of Goods Sold and write physical inventory back (In Cents).
        """
        tx_id = f"tx_return_{uuid.uuid4().hex[:8]}"
        entries = [
            LedgerEntry(account=ACCOUNT_PATHS["Inventory"], type="debit", amount=total_cogs),
            LedgerEntry(account=ACCOUNT_PATHS["Cost of Goods Sold"], type="credit", amount=total_cogs)
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
    def _compile_principal_pit(event: OLPEvent, total_cogs: float) -> CompilationResult:
        """
        Rule A: Principal + Physical/Digital + Point-in-Time (In Cents)
        """
        tx_id = f"tx_pit_{uuid.uuid4().hex[:8]}"
        ctx = event.accounting_context
        
        debit_asset = "Accounts Receivable" if ctx.payment_method == "invoice" else "Cash"
        base_amount = event.amount - event.tax_amount
        
        if event.event_type == "payment_received":
            debit_cash = event.amount - event.processing_fee if debit_asset == "Cash" else event.amount
            entries = [
                LedgerEntry(account=ACCOUNT_PATHS[debit_asset], type="debit", amount=debit_cash),
                LedgerEntry(account=ACCOUNT_PATHS["Deferred Revenue"], type="credit", amount=base_amount),
                LedgerEntry(account=ACCOUNT_PATHS["Sales Tax Payable"], type="credit", amount=event.tax_amount)
            ]
            if event.processing_fee > 0 and debit_asset == "Cash":
                entries.append(LedgerEntry(account=ACCOUNT_PATHS["Payment Processing Expense"], type="debit", amount=event.processing_fee))
            desc = f"OLP Principal Payment Received (Deferred): {event.description}"
            
        elif event.event_type == "fulfillment_completed":
            entries = [
                LedgerEntry(account=ACCOUNT_PATHS["Deferred Revenue"], type="debit", amount=base_amount),
                LedgerEntry(account=ACCOUNT_PATHS["Gross Revenue"], type="credit", amount=base_amount)
            ]
            if total_cogs > 0:
                entries.append(LedgerEntry(account=ACCOUNT_PATHS["Cost of Goods Sold"], type="debit", amount=total_cogs))
                entries.append(LedgerEntry(account=ACCOUNT_PATHS["Inventory"], type="credit", amount=total_cogs))
            desc = f"OLP Principal Delivery / Fulfillment (Revenue Recognized): {event.description}"
            
        else: # immediate_sale
            debit_cash = event.amount - event.processing_fee if debit_asset == "Cash" else event.amount
            entries = [
                LedgerEntry(account=ACCOUNT_PATHS[debit_asset], type="debit", amount=debit_cash),
                LedgerEntry(account=ACCOUNT_PATHS["Gross Revenue"], type="credit", amount=base_amount),
                LedgerEntry(account=ACCOUNT_PATHS["Sales Tax Payable"], type="credit", amount=event.tax_amount)
            ]
            if event.processing_fee > 0 and debit_asset == "Cash":
                entries.append(LedgerEntry(account=ACCOUNT_PATHS["Payment Processing Expense"], type="debit", amount=event.processing_fee))
            if total_cogs > 0:
                entries.append(LedgerEntry(account=ACCOUNT_PATHS["Cost of Goods Sold"], type="debit", amount=total_cogs))
                entries.append(LedgerEntry(account=ACCOUNT_PATHS["Inventory"], type="credit", amount=total_cogs))
            desc = f"OLP Principal Immediate Sale booking for: {event.description}"

        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            status="posted",
            description=desc,
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
        debit_asset = "Accounts Receivable" if ctx.payment_method == "invoice" else "Cash"
        base_amount = event.amount - event.tax_amount
        debit_cash = event.amount - event.processing_fee if debit_asset == "Cash" else event.amount
        
        # Initial booking transaction
        init_tx_id = f"tx_init_{uuid.uuid4().hex[:8]}"
        init_entries = [
            LedgerEntry(account=ACCOUNT_PATHS[debit_asset], type="debit", amount=debit_cash),
            LedgerEntry(account=ACCOUNT_PATHS["Deferred Revenue"], type="credit", amount=base_amount),
            LedgerEntry(account=ACCOUNT_PATHS["Sales Tax Payable"], type="credit", amount=event.tax_amount)
        ]
        if event.processing_fee > 0 and debit_asset == "Cash":
            init_entries.append(LedgerEntry(account=ACCOUNT_PATHS["Payment Processing Expense"], type="debit", amount=event.processing_fee))
            
        init_tx = Transaction(
            transaction_id=init_tx_id,
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            status="posted",
            description=f"OLP Principal Initial Over-Time booking for: {event.description}",
            entries=init_entries
        )

        # Generate amortization schedules
        amort_txs = []
        monthly_amt = base_amount // term
        accumulated = 0

        event_date = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
        
        for i in range(1, term + 1):
            if i == term:
                current_monthly_amt = base_amount - accumulated
            else:
                current_monthly_amt = monthly_amt
                accumulated += current_monthly_amt

            year = event_date.year + (event_date.month - 1 + i) // 12
            month = (event_date.month - 1 + i) % 12 + 1
            day = min(event_date.day, 28)
            amort_date = date(year, month, day).isoformat() + "T00:00:00Z"

            amort_tx_id = f"tx_amort_{i}_{uuid.uuid4().hex[:8]}"
            amort_entries = [
                LedgerEntry(account=ACCOUNT_PATHS["Deferred Revenue"], type="debit", amount=current_monthly_amt),
                LedgerEntry(account=ACCOUNT_PATHS["Subscription Revenue"], type="credit", amount=current_monthly_amt)
            ]
            
            amort_tx = Transaction(
                transaction_id=amort_tx_id,
                source_event_id=event.event_id,
                idempotency_key=event.idempotency_key,
                date=amort_date,
                status="posted",
                description=f"OLP Amortization Month {i}/{term} for: {event.description}",
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
        debit_asset = "Accounts Receivable" if ctx.payment_method == "invoice" else "Cash"
        debit_cash = event.amount - event.processing_fee if debit_asset == "Cash" else event.amount
        
        base_amount = event.amount - event.tax_amount
        # Perform multiplication first, then divide by 100 or multiply cut% directly to keep it in integer cents
        commission = int(base_amount * ctx.platform_fee_percent)
        vendor_cut = base_amount - commission

        tx_id = f"tx_agent_pit_{uuid.uuid4().hex[:8]}"
        
        if event.event_type == "payment_received":
            entries = [
                LedgerEntry(account=ACCOUNT_PATHS[debit_asset], type="debit", amount=debit_cash),
                LedgerEntry(account=ACCOUNT_PATHS["Deferred Payable (Vendor)"], type="credit", amount=vendor_cut),
                LedgerEntry(account=ACCOUNT_PATHS["Deferred Commission Revenue"], type="credit", amount=commission),
                LedgerEntry(account=ACCOUNT_PATHS["Sales Tax Payable"], type="credit", amount=event.tax_amount)
            ]
            if event.processing_fee > 0 and debit_asset == "Cash":
                entries.append(LedgerEntry(account=ACCOUNT_PATHS["Payment Processing Expense"], type="debit", amount=event.processing_fee))
            desc = f"OLP Agent Payment Received (Deferred): {event.description}"
            
        elif event.event_type == "fulfillment_completed":
            entries = [
                LedgerEntry(account=ACCOUNT_PATHS["Deferred Payable (Vendor)"], type="debit", amount=vendor_cut),
                LedgerEntry(account=ACCOUNT_PATHS["Accounts Payable (Vendor)"], type="credit", amount=vendor_cut),
                LedgerEntry(account=ACCOUNT_PATHS["Deferred Commission Revenue"], type="debit", amount=commission),
                LedgerEntry(account=ACCOUNT_PATHS["Commission Revenue"], type="credit", amount=commission)
            ]
            desc = f"OLP Agent Fulfillment (Revenue & Payable Recognized): {event.description}"
            
        else: # immediate_sale
            entries = [
                LedgerEntry(account=ACCOUNT_PATHS[debit_asset], type="debit", amount=debit_cash),
                LedgerEntry(account=ACCOUNT_PATHS["Accounts Payable (Vendor)"], type="credit", amount=vendor_cut),
                LedgerEntry(account=ACCOUNT_PATHS["Commission Revenue"], type="credit", amount=commission),
                LedgerEntry(account=ACCOUNT_PATHS["Sales Tax Payable"], type="credit", amount=event.tax_amount)
            ]
            if event.processing_fee > 0 and debit_asset == "Cash":
                entries.append(LedgerEntry(account=ACCOUNT_PATHS["Payment Processing Expense"], type="debit", amount=event.processing_fee))
            desc = f"OLP Agent Immediate Sale booking for: {event.description}"
        
        tx = Transaction(
            transaction_id=tx_id,
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            status="posted",
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
        debit_asset = "Accounts Receivable" if ctx.payment_method == "invoice" else "Cash"
        debit_cash = event.amount - event.processing_fee if debit_asset == "Cash" else event.amount
        
        base_amount = event.amount - event.tax_amount
        commission = int(base_amount * ctx.platform_fee_percent)
        vendor_cut = base_amount - commission

        # Initial booking transaction
        init_tx_id = f"tx_agent_init_{uuid.uuid4().hex[:8]}"
        init_entries = [
            LedgerEntry(account=ACCOUNT_PATHS[debit_asset], type="debit", amount=debit_cash),
            LedgerEntry(account=ACCOUNT_PATHS["Deferred Payable (Vendor)"], type="credit", amount=vendor_cut),
            LedgerEntry(account=ACCOUNT_PATHS["Deferred Commission Revenue"], type="credit", amount=commission),
            LedgerEntry(account=ACCOUNT_PATHS["Sales Tax Payable"], type="credit", amount=event.tax_amount)
        ]
        if event.processing_fee > 0 and debit_asset == "Cash":
            init_entries.append(LedgerEntry(account=ACCOUNT_PATHS["Payment Processing Expense"], type="debit", amount=event.processing_fee))
            
        init_tx = Transaction(
            transaction_id=init_tx_id,
            source_event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            date=event.timestamp,
            status="posted",
            description=f"OLP Agent Initial Over-Time booking for: {event.description}",
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
                LedgerEntry(account=ACCOUNT_PATHS["Deferred Payable (Vendor)"], type="debit", amount=curr_vendor),
                LedgerEntry(account=ACCOUNT_PATHS["Accounts Payable (Vendor)"], type="credit", amount=curr_vendor),
                LedgerEntry(account=ACCOUNT_PATHS["Deferred Commission Revenue"], type="debit", amount=curr_comm),
                LedgerEntry(account=ACCOUNT_PATHS["Commission Revenue"], type="credit", amount=curr_comm)
            ]
            
            amort_tx = Transaction(
                transaction_id=amort_tx_id,
                source_event_id=event.event_id,
                idempotency_key=event.idempotency_key,
                date=amort_date,
                status="posted",
                description=f"OLP Agent Amortization Month {i}/{term} for: {event.description}",
                entries=amort_entries
            )
            amort_txs.append(amort_tx)

        return CompilationResult(initial_transaction=init_tx, amortization_schedule=amort_txs)
