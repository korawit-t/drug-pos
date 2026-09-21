from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import Lot, Product, ProductUnit, Purchase, PurchaseItem, StockMovement, Supplier


class StockError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class Allocation:
    lot: Lot
    qty: int  # base units


def sellable_lots(product: Product, today=None):
    """Lots that may be sold, first-expiring first (FEFO). A lot is sellable through its expiry date."""
    today = today or timezone.localdate()
    return Lot.objects.filter(product=product, qty_on_hand__gt=0, expiry_date__gte=today).order_by(
        "expiry_date", "id"
    )


def expired_qty(product: Product, today=None) -> int:
    today = today or timezone.localdate()
    return (
        Lot.objects.filter(product=product, qty_on_hand__gt=0, expiry_date__lt=today).aggregate(
            s=Sum("qty_on_hand")
        )["s"]
        or 0
    )


def allocate_fefo(product: Product, base_qty: int, today=None) -> list[Allocation]:
    """Pick lots for a sale, earliest expiry first. Expired lots are never picked."""
    lots = list(sellable_lots(product, today))
    remaining = base_qty
    allocations = []
    for lot in lots:
        if remaining == 0:
            break
        take = min(lot.qty_on_hand, remaining)
        allocations.append(Allocation(lot, take))
        remaining -= take
    if remaining > 0:
        available = sum(lot.qty_on_hand for lot in lots)
        message = f"{product.display_name}: สต็อกไม่พอ มี {available} {product.base_unit} ต้องการ {base_qty}"
        if expired := expired_qty(product, today):
            message += f" (มียาหมดอายุอีก {expired} {product.base_unit} ขายไม่ได้)"
        raise StockError(message)
    return allocations


def record_movement(lot: Lot, kind: str, qty: int, *, user=None, purchase_item=None, note="") -> StockMovement:
    """
    The only place stock changes: one ledger row plus the cached balance on
    the lot, committed together.
    """
    with transaction.atomic():
        movement = StockMovement.objects.create(
            lot=lot, kind=kind, qty=qty, created_by=user, purchase_item=purchase_item, note=note[:200]
        )
        Lot.objects.filter(pk=lot.pk).update(qty_on_hand=F("qty_on_hand") + qty)
        lot.refresh_from_db(fields=["qty_on_hand"])
        if lot.qty_on_hand < 0:
            raise StockError(f"{lot}: สต็อกติดลบ")
    return movement


def post_purchase(purchase: Purchase, user) -> Purchase:
    """บันทึกใบรับยาเข้าสต็อก: สร้าง/เติม lot และลง ledger ทีละรายการ"""
    with transaction.atomic():
        purchase = Purchase.objects.get(pk=purchase.pk)
        if purchase.status == Purchase.Status.POSTED:
            raise StockError("ใบรับยานี้บันทึกเข้าสต็อกไปแล้ว")
        if not purchase.is_opening_balance and not purchase.supplier_id:
            raise StockError("ใบรับยาต้องระบุผู้ขาย (ยกเว้นยอดยกมา)")
        items = list(purchase.items.select_related("unit__product").order_by("id"))
        if not items:
            raise StockError("ใบรับยายังไม่มีรายการ")

        kind = StockMovement.Kind.OPENING if purchase.is_opening_balance else StockMovement.Kind.RECEIVE
        for number, item in enumerate(items, 1):
            product = item.unit.product
            lot_no = item.lot_no.strip()
            if not lot_no:
                raise StockError(f"รายการที่ {number} ({product.display_name}): ต้องกรอกเลขที่ lot")
            if item.expiry_date is None:
                raise StockError(f"รายการที่ {number} ({product.display_name}): ต้องกรอกวันหมดอายุ")
            if not purchase.is_opening_balance and item.expiry_date <= purchase.received_date:
                raise StockError(f"{product.display_name} lot {lot_no} หมดอายุแล้ว รับเข้าไม่ได้")
            if item.unit_cost is None and not purchase.is_opening_balance:
                raise StockError(f"รายการที่ {number} ({product.display_name}): ต้องกรอกราคาทุน (ของแถมใส่ 0)")
            unit_cost = item.unit_cost or Decimal("0")  # opening balance may not know old costs
            lot, _ = Lot.objects.get_or_create(
                product=product,
                lot_no=lot_no,
                expiry_date=item.expiry_date,
                defaults={"cost_per_base": (unit_cost / item.unit.factor).quantize(Decimal("0.0001"))},
            )
            record_movement(lot, kind, item.base_qty, user=user, purchase_item=item, note=str(purchase))
            item.lot = lot
            item.save(update_fields=["lot"])

        purchase.status = Purchase.Status.POSTED
        purchase.posted_at = timezone.now()
        purchase.posted_by = user
        purchase.save(update_fields=["status", "posted_at", "posted_by"])
    return purchase


@dataclass
class PurchaseLine:
    unit_id: int
    qty: int
    lot_no: str = ""
    expiry_date: date | None = None
    unit_cost: Decimal | None = None  # None: not entered yet (drafts only)


@dataclass
class PurchaseData:
    received_date: date
    is_opening_balance: bool = False
    supplier_id: int | None = None
    invoice_no: str = ""
    invoice_date: date | None = None
    note: str = ""
    lines: list[PurchaseLine] = field(default_factory=list)


def save_purchase(data: PurchaseData, user, purchase: Purchase | None = None, post: bool = False) -> Purchase:
    """
    Create or update a receiving document from the counter screen. A draft may
    be incomplete; with post=True it is also posted to stock, and if posting
    fails nothing is saved at all.
    """
    with transaction.atomic():
        if purchase is not None:
            purchase = Purchase.objects.get(pk=purchase.pk)
            if purchase.status == Purchase.Status.POSTED:
                raise StockError("ใบรับยานี้บันทึกเข้าสต็อกแล้ว แก้ไขไม่ได้")

        supplier = None
        if data.supplier_id:
            supplier = Supplier.objects.filter(pk=data.supplier_id).first()
            if supplier is None:
                raise StockError("ไม่พบผู้ขาย")
        if data.received_date > timezone.localdate():
            raise StockError("วันที่รับยาเป็นวันในอนาคต")
        invoice_no = data.invoice_no.strip()
        if supplier and invoice_no:
            duplicate = Purchase.objects.filter(supplier=supplier, invoice_no=invoice_no)
            if purchase is not None:
                duplicate = duplicate.exclude(pk=purchase.pk)
            if duplicate.exists():
                raise StockError(f"ใบกำกับเลขที่ {invoice_no} ของ {supplier} บันทึกไว้แล้ว")

        units = ProductUnit.objects.select_related("product").in_bulk([line.unit_id for line in data.lines])
        for number, line in enumerate(data.lines, 1):
            unit = units.get(line.unit_id)
            if unit is None or not unit.product.is_active:
                raise StockError(f"รายการที่ {number}: ไม่พบสินค้าหรือเลิกใช้งานแล้ว")
            if line.qty < 1:
                raise StockError(f"รายการที่ {number} ({unit.product.display_name}): จำนวนต้องมากกว่า 0")
            if line.unit_cost is not None and line.unit_cost < 0:
                raise StockError(f"รายการที่ {number} ({unit.product.display_name}): ราคาทุนติดลบไม่ได้")

        if purchase is None:
            purchase = Purchase(created_by=user if getattr(user, "is_authenticated", False) else None)
        purchase.is_opening_balance = data.is_opening_balance
        purchase.supplier = supplier
        purchase.invoice_no = invoice_no
        purchase.invoice_date = data.invoice_date
        purchase.received_date = data.received_date
        purchase.note = data.note.strip()[:200]
        purchase.save()

        # Drafts own their lines outright (nothing is in stock yet), so replace them.
        purchase.items.all().delete()
        PurchaseItem.objects.bulk_create(
            PurchaseItem(
                purchase=purchase,
                unit=units[line.unit_id],
                qty=line.qty,
                lot_no=line.lot_no.strip()[:50],
                expiry_date=line.expiry_date,
                unit_cost=line.unit_cost,
            )
            for line in data.lines
        )
        if post:
            post_purchase(purchase, user)
    purchase.refresh_from_db()
    return purchase


def delete_draft(purchase: Purchase) -> None:
    with transaction.atomic():
        purchase = Purchase.objects.get(pk=purchase.pk)
        if purchase.status == Purchase.Status.POSTED:
            raise StockError("ใบรับยาที่บันทึกเข้าสต็อกแล้วลบไม่ได้")
        purchase.delete()


def last_costs(unit_ids: list[int]) -> dict[int, Decimal]:
    """ราคาทุนครั้งล่าสุดของแต่ละหน่วย จากใบรับยาที่บันทึกเข้าสต็อกแล้ว (ไม่นับยอดยกมา)"""
    costs = {}
    for unit_id in unit_ids:
        cost = (
            PurchaseItem.objects.filter(
                unit_id=unit_id,
                purchase__status=Purchase.Status.POSTED,
                purchase__is_opening_balance=False,
            )
            .exclude(unit_cost=None)
            .order_by("-purchase__received_date", "-id")
            .values_list("unit_cost", flat=True)
            .first()
        )
        if cost is not None:
            costs[unit_id] = cost
    return costs


def stock_mismatches() -> list[Lot]:
    """Lots whose cached balance doesn't match the ledger. Should always be empty."""
    return list(
        Lot.objects.annotate(ledger=Coalesce(Sum("movements__qty"), 0)).exclude(qty_on_hand=F("ledger"))
    )
