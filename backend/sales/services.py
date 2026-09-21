import hashlib
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from datetime import timezone as dt_timezone
from decimal import Decimal

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from accounts.models import User
from inventory.models import PriceLevel, ProductUnit, StockMovement
from inventory.services import StockError, allocate_fefo, record_movement

from .models import Customer, Sale, SaleItem, SaleItemLot

DISPENSE_SALT = "drugpos.dispense"
CENTS = Decimal("0.01")


class SaleError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# --- Pharmacist confirmation -------------------------------------------------
#
# After a pharmacist enters their PIN, each confirmed line gets a signed token
# that pins down exactly what was approved: this bill, this unit, this qty,
# this label text. Checkout accepts a line only with a matching, unexpired
# token — so changing anything after confirmation means confirming again.


def _dosage_digest(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


def sign_dispense(pharmacist: User, client_uuid, unit_id: int, qty: int, dosage_text: str) -> str:
    return signing.dumps(
        {
            "ph": pharmacist.pk,
            "b": str(client_uuid),
            "u": unit_id,
            "q": qty,
            "d": _dosage_digest(dosage_text),
            "t": int(time.time()),
        },
        salt=DISPENSE_SALT,
    )


def check_dispense(token, client_uuid, unit_id: int, qty: int, dosage_text: str):
    """Returns (pharmacist, confirmed_at) if the token approves exactly this line, else None."""
    if not token:
        return None
    try:
        data = signing.loads(token, salt=DISPENSE_SALT, max_age=settings.DISPENSE_APPROVAL_MAX_AGE)
    except signing.BadSignature:
        return None
    expected = {"b": str(client_uuid), "u": unit_id, "q": qty, "d": _dosage_digest(dosage_text)}
    if any(data.get(key) != value for key, value in expected.items()):
        return None
    pharmacist = User.objects.filter(pk=data.get("ph"), is_active=True, role=User.Role.PHARMACIST).first()
    if pharmacist is None:
        return None
    return pharmacist, datetime.fromtimestamp(data["t"], tz=dt_timezone.utc)


# --- Checkout ----------------------------------------------------------------


@dataclass
class CartLine:
    unit_id: int
    qty: int
    dosage_text: str = ""
    approval: str | None = None


@dataclass
class CheckoutRequest:
    client_uuid: uuid.UUID
    payment_method: str
    lines: list[CartLine] = field(default_factory=list)
    price_level: int = 1
    customer_id: int | None = None
    buyer_name: str = ""
    cash_received: Decimal | None = None
    is_prescription: bool = False
    rx_prescriber: str = ""
    rx_prescriber_license: str = ""
    rx_facility: str = ""
    rx_date: date | None = None


def next_sale_number(today: date) -> str:
    prefix = today.strftime("%y%m%d") + "-"
    last = (
        Sale.objects.filter(number__startswith=prefix).order_by("-number").values_list("number", flat=True).first()
    )
    seq = int(last.split("-")[1]) + 1 if last else 1
    return f"{prefix}{seq:04d}"


def checkout(req: CheckoutRequest, cashier: User) -> Sale:
    """
    Save a sale. Prices are recomputed here from the database — the counter's
    numbers are only a preview. Stock is taken FEFO inside one transaction.
    Calling again with the same client_uuid returns the sale already saved.
    """
    if existing := Sale.objects.filter(client_uuid=req.client_uuid).first():
        return existing
    if not req.lines:
        raise SaleError("ยังไม่มีรายการในบิล")
    if req.payment_method not in Sale.Payment.values:
        raise SaleError("วิธีชำระเงินไม่ถูกต้อง")

    try:
        with transaction.atomic():
            # Checked again under the write lock, in case the same bill was submitted twice at once.
            if existing := Sale.objects.filter(client_uuid=req.client_uuid).first():
                return existing
            return _checkout_locked(req, cashier)
    except StockError as exc:
        raise SaleError(exc.message) from exc


def _checkout_locked(req: CheckoutRequest, cashier: User) -> Sale:
    level = PriceLevel.objects.filter(pk=req.price_level).first()
    if level is None:
        raise SaleError("ระดับราคาไม่ถูกต้อง")
    customer = None
    if req.customer_id:
        customer = Customer.objects.filter(pk=req.customer_id).first()
        if customer is None:
            raise SaleError("ไม่พบข้อมูลลูกค้า")

    units = ProductUnit.objects.select_related("product").in_bulk([line.unit_id for line in req.lines])
    prepared = []
    needs_prescription = needs_buyer_name = False
    for line in req.lines:
        unit = units.get(line.unit_id)
        if unit is None or not unit.product.is_active:
            raise SaleError("มีสินค้าในบิลที่ไม่พบหรือเลิกขายแล้ว")
        if line.qty < 1:
            raise SaleError(f"{unit.product.display_name}: จำนวนต้องมากกว่า 0")
        product = unit.product
        dosage = line.dosage_text.strip()
        pharmacist = confirmed_at = None
        if product.needs_pharmacist:
            approved = check_dispense(line.approval, req.client_uuid, unit.pk, line.qty, dosage)
            if approved is None:
                raise SaleError(f"{product.display_name} ยังไม่ได้รับการยืนยันจากเภสัชกร", status=409)
            pharmacist, confirmed_at = approved
        needs_prescription |= product.needs_prescription
        needs_buyer_name |= product.needs_buyer_name
        prepared.append((line, unit, product, dosage, pharmacist, confirmed_at, unit.price_for(level.level)))

    buyer_name = req.buyer_name.strip() or (customer.name if customer else "")
    if needs_buyer_name and not buyer_name:
        raise SaleError("มียาที่ต้องลงบัญชี ขย.11 ต้องระบุชื่อผู้ซื้อ")
    if needs_prescription and not (req.rx_prescriber.strip() and req.rx_facility.strip()):
        raise SaleError("มียาควบคุมพิเศษ ต้องกรอกข้อมูลใบสั่งยา (ผู้สั่งจ่ายและสถานพยาบาล)")
    if req.rx_date and req.rx_date > timezone.localdate():
        # Usually a พ.ศ. year typed into a ค.ศ. date field.
        raise SaleError("วันที่ในใบสั่งยาอยู่ในอนาคต — ถ้ากรอกปีเป็น พ.ศ. ให้เปลี่ยนเป็น ค.ศ.")

    total = sum((price * line.qty for line, *_, price in prepared), Decimal("0")).quantize(CENTS)
    cash_received = change = None
    if req.payment_method == Sale.Payment.CASH:
        if req.cash_received is None or req.cash_received < total:
            raise SaleError("รับเงินไม่พอ")
        cash_received = Decimal(req.cash_received).quantize(CENTS)
        change = cash_received - total

    sale = Sale.objects.create(
        number=next_sale_number(timezone.localdate()),
        client_uuid=req.client_uuid,
        cashier=cashier,
        customer=customer,
        buyer_name=buyer_name,
        price_level=level,
        total=total,
        payment_method=req.payment_method,
        cash_received=cash_received,
        change=change,
        is_prescription=req.is_prescription or needs_prescription,
        rx_prescriber=req.rx_prescriber.strip(),
        rx_prescriber_license=req.rx_prescriber_license.strip(),
        rx_facility=req.rx_facility.strip(),
        rx_date=req.rx_date,
    )
    for line, unit, product, dosage, pharmacist, confirmed_at, price in prepared:
        base_qty = line.qty * unit.factor
        item = SaleItem.objects.create(
            sale=sale,
            product=product,
            unit=unit,
            description=product.display_name,
            unit_name=unit.name,
            category=product.category,
            in_ky11_list=product.in_ky11_list,
            in_ky13_list=product.in_ky13_list,
            qty=line.qty,
            base_qty=base_qty,
            unit_price=price,
            line_total=(price * line.qty).quantize(CENTS),
            dosage_text=dosage,
            confirmed_by=pharmacist,
            confirmed_at=confirmed_at,
        )
        for allocation in allocate_fefo(product, base_qty):
            movement = record_movement(
                allocation.lot, StockMovement.Kind.SALE, -allocation.qty, user=cashier, note=f"บิล {sale.number}"
            )
            SaleItemLot.objects.create(sale_item=item, lot=allocation.lot, qty=allocation.qty, movement=movement)
    return sale


# --- Void --------------------------------------------------------------------


def void_sale(sale: Sale, approved_by: User, reason: str) -> Sale:
    """ยกเลิกบิล: คืนสต็อกเข้า lot เดิมด้วย movement กลับรายการ บิลยังอยู่ แค่เปลี่ยนสถานะ"""
    reason = reason.strip()
    if not reason:
        raise SaleError("ต้องระบุเหตุผลที่ยกเลิก")
    with transaction.atomic():
        sale = Sale.objects.get(pk=sale.pk)
        if sale.status == Sale.Status.VOIDED:
            raise SaleError("บิลนี้ถูกยกเลิกไปแล้ว")
        for allocation in SaleItemLot.objects.filter(sale_item__sale=sale).select_related("lot"):
            allocation.void_movement = record_movement(
                allocation.lot, StockMovement.Kind.VOID, allocation.qty, user=approved_by,
                note=f"ยกเลิกบิล {sale.number}",
            )
            allocation.save(update_fields=["void_movement"])
        sale.status = Sale.Status.VOIDED
        sale.voided_at = timezone.now()
        sale.voided_by = approved_by
        sale.void_reason = reason[:200]
        sale.save(update_fields=["status", "voided_at", "voided_by", "void_reason"])
    return sale


def daily_summary(day: date) -> dict:
    result = Sale.objects.filter(created_at__date=day, status=Sale.Status.COMPLETED).aggregate(
        n=Count("id"),
        all_total=Sum("total"),
        cash_total=Sum("total", filter=Q(payment_method=Sale.Payment.CASH)),
        transfer_total=Sum("total", filter=Q(payment_method=Sale.Payment.TRANSFER)),
    )
    zero = Decimal("0.00")
    return {
        "count": result["n"],
        "total": result["all_total"] or zero,
        "cash": result["cash_total"] or zero,
        "transfer": result["transfer_total"] or zero,
    }
