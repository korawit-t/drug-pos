from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import Lot, Product, Purchase, StockMovement


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
        items = list(purchase.items.select_related("unit__product"))
        if not items:
            raise StockError("ใบรับยายังไม่มีรายการ")

        kind = StockMovement.Kind.OPENING if purchase.is_opening_balance else StockMovement.Kind.RECEIVE
        for item in items:
            product = item.unit.product
            lot_no = item.lot_no.strip()
            if not purchase.is_opening_balance and item.expiry_date <= purchase.received_date:
                raise StockError(f"{product.display_name} lot {lot_no} หมดอายุแล้ว รับเข้าไม่ได้")
            lot, _ = Lot.objects.get_or_create(
                product=product,
                lot_no=lot_no,
                expiry_date=item.expiry_date,
                defaults={"cost_per_base": (item.unit_cost / item.unit.factor).quantize(Decimal("0.0001"))},
            )
            record_movement(lot, kind, item.base_qty, user=user, purchase_item=item, note=str(purchase))
            item.lot = lot
            item.save(update_fields=["lot"])

        purchase.status = Purchase.Status.POSTED
        purchase.posted_at = timezone.now()
        purchase.posted_by = user
        purchase.save(update_fields=["status", "posted_at", "posted_by"])
    return purchase


def stock_mismatches() -> list[Lot]:
    """Lots whose cached balance doesn't match the ledger. Should always be empty."""
    return list(
        Lot.objects.annotate(ledger=Coalesce(Sum("movements__qty"), 0)).exclude(qty_on_hand=F("ledger"))
    )
