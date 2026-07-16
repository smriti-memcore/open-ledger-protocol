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
    term_months: Optional[int] = None
    platform_fee_percent: float = 0.20
    payment_method: str = "card"    # "card" | "invoice"
    billing_status: str = "billed"  # "billed" | "unbilled"

@dataclass
class LineItem:
    item_id: str
    price: int                      # In cents
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
    tax_jurisdiction: Optional[str] = None # Local tax region (e.g. "DE", "US-CA")
    processing_fee: int = 0         # In cents
    discount_amount: int = 0        # In cents
    capitalized_costs: int = 0      # In cents
    functional_amount: Optional[int] = None
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
    "Inventory": "/assets/inventory",
    "Deferred Contract Costs": "/assets/deferred_costs/commissions",
    "Deferred Revenue": "/liabilities/deferred/revenue",
    "Deferred Payable (Vendor)": "/liabilities/deferred/payable_vendor",
    "Deferred Commission Revenue": "/liabilities/deferred/commission",
    "Accounts Payable (Vendor)": "/liabilities/payables/vendor",
    "Sales Tax Payable": "/liabilities/tax/payable",
    "Commissions Payable": "/liabilities/payables/commissions",
    "Gross Revenue": "/equity/revenue/gross",
    "Subscription Revenue": "/equity/revenue/subscription",
    "Commission Revenue": "/equity/revenue/commission",
    "Intercompany Revenue": "/equity/revenue/intercompany",
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
                cogs_estimate=item.cogs_estimate
            ))
            
        event.line_items = new_items
        return event

    @staticmethod
    def _get_tax_account(event: OLPEvent) -> str:
        """
        Dynamically route local tax credits for MNC jurisdictions.
        """
        if event.tax_jurisdiction:
            clean_jurisdiction = event.tax_jurisdiction.lower().replace("-", "_")
            return f"/liabilities/tax/payable/{clean_jurisdiction}"
        return ACCOUNT_PATHS["Sales Tax Payable"]

    @staticmethod
    def compile_event(event: OLPEvent) -> CompilationResult:
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

        # Route lifecycle & decoupled pipeline events
        if event.event_type == "payment_settled":
            res = OLPEngine._compile_payment_settled(event)
        elif event.event_type == "refund_issued":
            res = OLPEngine._compile_refund_issued(event)
        elif event.event_type == "goods_returned":
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
            if ctx.recognition == "point_in_time":
                res = OLPEngine._compile_principal_pit(event, total_cogs)
            else:
                res = OLPEngine._compile_principal_ot(event)
        else: # agent
            if ctx.recognition == "point_in_time":
                res = OLPEngine._compile_agent_pit(event)
            else:
                res = OLPEngine._compile_agent_ot(event)

        # Apply Intercompany Transfer (ASC 810) if partner entity is defined and different
        if event.intercompany_entity_id and event.intercompany_entity_id != ctx.entity_id:
            # 1. Update billing entity ledger (German ledger): debit intercompany expense, credit intercompany payable
            pay_acct = f"/liabilities/payables/intercompany_{event.intercompany_entity_id.lower()}"
            res.initial_transaction.entries.append(
                LedgerEntry(account=ACCOUNT_PATHS["Intercompany Expense"], type="debit", amount=event.intercompany_transfer_amount)
            )
            res.initial_transaction.entries.append(
                LedgerEntry(account=pay_acct, type="credit", amount=event.intercompany_transfer_amount)
            )
            
            # 2. Build partner ledger transaction: debit intercompany receivable, credit intercompany revenue
            rec_acct = f"/assets/receivables/intercompany_{ctx.entity_id.lower()}"
            partner_tx = Transaction(
                transaction_id=f"tx_ic_{uuid.uuid4().hex[:8]}",
                source_event_id=event.event_id,
                idempotency_key=f"{event.idempotency_key}_ic",
                date=event.timestamp,
                status="posted",
                description=f"OLP Intercompany Revenue Transfer: {ctx.entity_id} to {event.intercompany_entity_id}",
                entries=[
                    LedgerEntry(account=rec_acct, type="debit", amount=event.intercompany_transfer_amount),
                    LedgerEntry(account=ACCOUNT_PATHS["Intercompany Revenue"], type="credit", amount=event.intercompany_transfer_amount)
                ]
            )
            res.intercompany_transaction = partner_tx

        return res

    @staticmethod
    def _compile_order_placed(event: OLPEvent) -> CompilationResult:
        tx_id = f"tx_ord_{uuid.uuid4().hex[:8]}"
        base_amount = event.amount - event.tax_amount
        tax_acct = OLPEngine._get_tax_account(event)
        
        entries = [
            LedgerEntry(account=ACCOUNT_PATHS["Order Clearing"], type="debit", amount=event.amount),
            LedgerEntry(account=ACCOUNT_PATHS["Gross Revenue"], type="credit", amount=base_amount),
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
            LedgerEntry(account=ACCOUNT_PATHS["Payment Clearing"], type="debit", amount=net_amount),
            LedgerEntry(account=ACCOUNT_PATHS["Payment Processing Expense"], type="debit", amount=event.processing_fee),
            LedgerEntry(account=ACCOUNT_PATHS["Order Clearing"], type="credit", amount=event.amount)
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
            LedgerEntry(account=ACCOUNT_PATHS["Cash"], type="debit", amount=event.amount),
            LedgerEntry(account=ACCOUNT_PATHS["Payment Clearing"], type="credit", amount=event.amount)
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
            LedgerEntry(account=ACCOUNT_PATHS["Cash"], type="debit", amount=debit_cash),
            LedgerEntry(account=ACCOUNT_PATHS["Accounts Receivable"], type="credit", amount=event.amount)
        ]
        
        if event.processing_fee > 0:
            entries.append(LedgerEntry(account=ACCOUNT_PATHS["Payment Processing Expense"], type="debit", amount=event.processing_fee))
            
        if fx_diff > 0:
            entries.append(LedgerEntry(account=ACCOUNT_PATHS["Gain on FX"], type="credit", amount=fx_diff))
        elif fx_diff < 0:
            entries.append(LedgerEntry(account=ACCOUNT_PATHS["Loss on FX"], type="debit", amount=abs(fx_diff)))
            
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
            LedgerEntry(account=ACCOUNT_PATHS["Refunds & Allowances"], type="debit", amount=base_refund),
            LedgerEntry(account=ACCOUNT_PATHS[credit_account], type="credit", amount=event.amount)
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
    def _compile_contract_billed(event: OLPEvent) -> CompilationResult:
        tx_id = f"tx_billed_{uuid.uuid4().hex[:8]}"
        entries = [
            LedgerEntry(account=ACCOUNT_PATHS["Accounts Receivable"], type="debit", amount=event.amount),
            LedgerEntry(account=ACCOUNT_PATHS["Contract Assets"], type="credit", amount=event.amount)
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
            LedgerEntry(account=ACCOUNT_PATHS["Bad Debt Expense"], type="debit", amount=event.amount),
            LedgerEntry(account=ACCOUNT_PATHS["Accounts Receivable"], type="credit", amount=event.amount)
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
    def _get_debit_asset_account(ctx: AccountingContext) -> str:
        if ctx.payment_method == "invoice":
            if ctx.billing_status == "unbilled":
                return ACCOUNT_PATHS["Contract Assets"]
            return ACCOUNT_PATHS["Accounts Receivable"]
        return ACCOUNT_PATHS["Cash"]

    @staticmethod
    def _compile_principal_pit(event: OLPEvent, total_cogs: float) -> CompilationResult:
        """
        Rule A: Principal + Physical/Digital + Point-in-Time (In Cents)
        """
        tx_id = f"tx_pit_{uuid.uuid4().hex[:8]}"
        ctx = event.accounting_context
        
        debit_account = OLPEngine._get_debit_asset_account(ctx)
        base_amount = event.amount - event.tax_amount
        tax_acct = OLPEngine._get_tax_account(event)
        
        if event.event_type == "payment_received":
            debit_cash = event.amount - event.processing_fee if debit_account == ACCOUNT_PATHS["Cash"] else event.amount
            entries = [
                LedgerEntry(account=debit_account, type="debit", amount=debit_cash),
                LedgerEntry(account=ACCOUNT_PATHS["Deferred Revenue"], type="credit", amount=base_amount),
                LedgerEntry(account=tax_acct, type="credit", amount=event.tax_amount)
            ]
            if event.processing_fee > 0 and debit_account == ACCOUNT_PATHS["Cash"]:
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
            debit_cash = event.amount - event.processing_fee if debit_account == ACCOUNT_PATHS["Cash"] else event.amount
            entries = [
                LedgerEntry(account=debit_account, type="debit", amount=debit_cash),
                LedgerEntry(account=ACCOUNT_PATHS["Gross Revenue"], type="credit", amount=base_amount),
                LedgerEntry(account=tax_acct, type="credit", amount=event.tax_amount)
            ]
            if event.processing_fee > 0 and debit_account == ACCOUNT_PATHS["Cash"]:
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
        debit_account = OLPEngine._get_debit_asset_account(ctx)
        base_amount = event.amount - event.tax_amount
        debit_cash = event.amount - event.processing_fee if debit_account == ACCOUNT_PATHS["Cash"] else event.amount
        tax_acct = OLPEngine._get_tax_account(event)
        
        # Initial booking transaction
        init_tx_id = f"tx_init_{uuid.uuid4().hex[:8]}"
        init_entries = [
            LedgerEntry(account=debit_account, type="debit", amount=debit_cash),
            LedgerEntry(account=ACCOUNT_PATHS["Deferred Revenue"], type="credit", amount=base_amount),
            LedgerEntry(account=tax_acct, type="credit", amount=event.tax_amount)
        ]
        if event.processing_fee > 0 and debit_account == ACCOUNT_PATHS["Cash"]:
            init_entries.append(LedgerEntry(account=ACCOUNT_PATHS["Payment Processing Expense"], type="debit", amount=event.processing_fee))
            
        # Add Capitalized Commissions
        if event.capitalized_costs > 0:
            init_entries.append(LedgerEntry(account=ACCOUNT_PATHS["Deferred Contract Costs"], type="debit", amount=event.capitalized_costs))
            init_entries.append(LedgerEntry(account=ACCOUNT_PATHS["Commissions Payable"], type="credit", amount=event.capitalized_costs))

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
                LedgerEntry(account=ACCOUNT_PATHS["Deferred Revenue"], type="debit", amount=current_monthly_rev),
                LedgerEntry(account=ACCOUNT_PATHS["Subscription Revenue"], type="credit", amount=current_monthly_rev)
            ]
            
            if event.capitalized_costs > 0:
                amort_entries.append(LedgerEntry(account=ACCOUNT_PATHS["Amortized Commission Expense"], type="debit", amount=current_monthly_cost))
                amort_entries.append(LedgerEntry(account=ACCOUNT_PATHS["Deferred Contract Costs"], type="credit", amount=current_monthly_cost))

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
        debit_account = OLPEngine._get_debit_asset_account(ctx)
        debit_cash = event.amount - event.processing_fee if debit_account == ACCOUNT_PATHS["Cash"] else event.amount
        
        base_amount = event.amount - event.tax_amount
        commission = int(base_amount * ctx.platform_fee_percent)
        vendor_cut = base_amount - commission
        tax_acct = OLPEngine._get_tax_account(event)

        tx_id = f"tx_agent_pit_{uuid.uuid4().hex[:8]}"
        
        if event.event_type == "payment_received":
            entries = [
                LedgerEntry(account=debit_account, type="debit", amount=debit_cash),
                LedgerEntry(account=ACCOUNT_PATHS["Deferred Payable (Vendor)"], type="credit", amount=vendor_cut),
                LedgerEntry(account=ACCOUNT_PATHS["Deferred Commission Revenue"], type="credit", amount=commission),
                LedgerEntry(account=tax_acct, type="credit", amount=event.tax_amount)
            ]
            if event.processing_fee > 0 and debit_account == ACCOUNT_PATHS["Cash"]:
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
                LedgerEntry(account=debit_account, type="debit", amount=debit_cash),
                LedgerEntry(account=ACCOUNT_PATHS["Accounts Payable (Vendor)"], type="credit", amount=vendor_cut),
                LedgerEntry(account=ACCOUNT_PATHS["Commission Revenue"], type="credit", amount=commission),
                LedgerEntry(account=tax_acct, type="credit", amount=event.tax_amount)
            ]
            if event.processing_fee > 0 and debit_account == ACCOUNT_PATHS["Cash"]:
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
        debit_account = OLPEngine._get_debit_asset_account(ctx)
        debit_cash = event.amount - event.processing_fee if debit_account == ACCOUNT_PATHS["Cash"] else event.amount
        
        base_amount = event.amount - event.tax_amount
        commission = int(base_amount * ctx.platform_fee_percent)
        vendor_cut = base_amount - commission
        tax_acct = OLPEngine._get_tax_account(event)

        # Initial booking transaction
        init_tx_id = f"tx_agent_init_{uuid.uuid4().hex[:8]}"
        init_entries = [
            LedgerEntry(account=debit_account, type="debit", amount=debit_cash),
            LedgerEntry(account=ACCOUNT_PATHS["Deferred Payable (Vendor)"], type="credit", amount=vendor_cut),
            LedgerEntry(account=ACCOUNT_PATHS["Deferred Commission Revenue"], type="credit", amount=commission),
            LedgerEntry(account=tax_acct, type="credit", amount=event.tax_amount)
        ]
        if event.processing_fee > 0 and debit_account == ACCOUNT_PATHS["Cash"]:
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
