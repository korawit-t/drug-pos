from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import (
    Lot,
    Product,
    ProductUnit,
    Purchase,
    PurchaseItem,
    StockCount,
    StockCountItem,
    StockMovement,
    Supplier,
)


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


# --- นับสต็อก / ปรับยอด -------------------------------------------------------


def countable_lots(product: Product):
    """lot ที่อยู่บนชั้นจริง — รวมของหมดอายุด้วย เพราะยังต้องนับและตัดทิ้ง"""
    return Lot.objects.filter(product=product, qty_on_hand__gt=0).order_by("expiry_date", "id")


def expired_lots(today=None):
    """ยาหมดอายุที่ยังค้างอยู่บนชั้นทั้งร้าน — ตัดทิ้งทีเดียวจากหน้านับสต็อกได้"""
    today = today or timezone.localdate()
    return Lot.objects.filter(qty_on_hand__gt=0, expiry_date__lt=today).order_by("expiry_date", "id")


@dataclass
class StockCountLine:
    lot_id: int
    system_qty: int  # ยอดที่คนนับเห็นตอนกรอก
    counted_qty: int | None = None  # None: ยังไม่ได้นับ (ร่างเท่านั้น)
    reason: str = ""
    note: str = ""


@dataclass
class StockCountData:
    counted_date: date
    note: str = ""
    lines: list[StockCountLine] = field(default_factory=list)


def save_stock_count(
    data: StockCountData, user, count: StockCount | None = None, post: bool = False, approved_by=None
) -> StockCount:
    """
    เก็บใบนับสต็อกจากหน้าจอ ร่างกรอกไม่ครบได้; post=True คือปรับยอดเข้าสต็อกด้วย
    ถ้าปรับไม่สำเร็จจะไม่บันทึกอะไรเลย
    """
    with transaction.atomic():
        if count is not None:
            count = StockCount.objects.get(pk=count.pk)
            if count.status == StockCount.Status.POSTED:
                raise StockError("ใบนับสต็อกนี้ปรับยอดแล้ว แก้ไขไม่ได้")
        if data.counted_date > timezone.localdate():
            raise StockError("วันที่นับเป็นวันในอนาคต")

        lots = Lot.objects.select_related("product").in_bulk([line.lot_id for line in data.lines])
        seen = set()
        for number, line in enumerate(data.lines, 1):
            lot = lots.get(line.lot_id)
            if lot is None:
                raise StockError(f"รายการที่ {number}: ไม่พบ lot นี้")
            if lot.pk in seen:
                raise StockError(f"{lot.product.display_name} lot {lot.lot_no}: อยู่ในใบนี้แล้ว")
            seen.add(lot.pk)
            if line.counted_qty is not None and line.counted_qty < 0:
                raise StockError(f"รายการที่ {number} ({lot.product.display_name}): จำนวนที่นับได้ติดลบไม่ได้")
            if line.reason and line.reason not in StockCountItem.Reason.values:
                raise StockError(f"รายการที่ {number} ({lot.product.display_name}): สาเหตุไม่ถูกต้อง")

        if count is None:
            count = StockCount(created_by=user if getattr(user, "is_authenticated", False) else None)
        count.counted_date = data.counted_date
        count.note = data.note.strip()[:200]
        count.save()

        # A draft owns its lines outright (nothing has touched stock yet), so replace them.
        count.items.all().delete()
        StockCountItem.objects.bulk_create(
            StockCountItem(
                count=count,
                lot=lots[line.lot_id],
                system_qty=line.system_qty,
                counted_qty=line.counted_qty,
                reason=line.reason,
                note=line.note.strip()[:200],
            )
            for line in data.lines
        )
        if post:
            post_stock_count(count, user, approved_by)
    count.refresh_from_db()
    return count


def post_stock_count(count: StockCount, user, approved_by) -> StockCount:
    """ปรับยอดตามที่นับได้: ตรวจทั้งใบก่อน แล้วลง ledger เฉพาะ lot ที่ยอดไม่ตรง"""
    with transaction.atomic():
        count = StockCount.objects.get(pk=count.pk)
        if count.status == StockCount.Status.POSTED:
            raise StockError("ใบนับสต็อกนี้ปรับยอดไปแล้ว")
        if approved_by is None or not approved_by.is_pharmacist:
            raise StockError("ต้องให้เภสัชกรอนุมัติก่อนปรับยอด")
        items = list(count.items.select_related("lot__product").order_by("id"))
        if not items:
            raise StockError("ใบนับสต็อกนี้ยังไม่มีรายการ")

        # ยอดล่าสุดจริง ๆ ไม่ใช่ค่าที่ติดมากับ select_related
        current = dict(Lot.objects.filter(pk__in=[item.lot_id for item in items]).values_list("pk", "qty_on_hand"))
        for number, item in enumerate(items, 1):
            lot = item.lot
            name = f"{lot.product.display_name} lot {lot.lot_no}"
            if item.counted_qty is None:
                raise StockError(f"รายการที่ {number} ({name}): ยังไม่ได้กรอกจำนวนที่นับได้")
            if current[lot.pk] != item.system_qty:
                raise StockError(
                    f"{name}: ยอดในระบบเปลี่ยนเป็น {current[lot.pk]} {lot.product.base_unit} ระหว่างที่นับ "
                    f"(ตอนนับคือ {item.system_qty}) — กด “ดึงยอดล่าสุด” แล้วตรวจรายการนี้อีกครั้ง"
                )
            if item.counted_qty != item.system_qty and not item.reason:
                raise StockError(f"รายการที่ {number} ({name}): เลือกสาเหตุที่ยอดไม่ตรง")
            if item.reason == StockCountItem.Reason.OTHER and not item.note.strip():
                raise StockError(f"รายการที่ {number} ({name}): เลือกสาเหตุ “อื่น ๆ” ต้องเขียนหมายเหตุด้วย")

        for item in items:
            difference = item.counted_qty - item.system_qty
            if not difference:
                continue  # นับแล้วตรง — เก็บไว้เป็นหลักฐานว่านับ ไม่ต้องลง ledger
            note = item.get_reason_display()
            if item.note.strip():
                note = f"{note}: {item.note.strip()}"
            item.movement = record_movement(
                item.lot, StockMovement.Kind.ADJUST, difference, user=approved_by, note=note
            )
            item.save(update_fields=["movement"])

        count.status = StockCount.Status.POSTED
        count.posted_at = timezone.now()
        count.posted_by = user if getattr(user, "is_authenticated", False) else None
        count.approved_by = approved_by
        count.save(update_fields=["status", "posted_at", "posted_by", "approved_by"])
    return count


def delete_count_draft(count: StockCount) -> None:
    with transaction.atomic():
        count = StockCount.objects.get(pk=count.pk)
        if count.status == StockCount.Status.POSTED:
            raise StockError("ใบนับสต็อกที่ปรับยอดแล้วลบไม่ได้")
        count.delete()
