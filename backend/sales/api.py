from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Field, Router, Schema
from ninja.errors import HttpError

from accounts.models import PinAttempt
from accounts.services import client_ip, verify_pin
from inventory.models import ProductUnit

from .models import Customer, HeldBill, Sale
from .services import CartLine, CheckoutRequest, checkout, daily_summary, sign_dispense, void_sale

router = Router(tags=["sales"])


# --- Customers ---------------------------------------------------------------


class CustomerOut(Schema):
    id: int
    name: str
    phone: str
    price_level: int
    allergies: str
    chronic_conditions: str


def _customer(c: Customer) -> dict:
    return {
        "id": c.pk,
        "name": c.name,
        "phone": c.phone,
        "price_level": c.price_level_id,
        "allergies": c.allergies,
        "chronic_conditions": c.chronic_conditions,
    }


@router.get("/customers", response=list[CustomerOut])
def search_customers(request, q: str = ""):
    customers = Customer.objects.all()
    if q := q.strip():
        customers = customers.filter(Q(name__icontains=q) | Q(phone__icontains=q))
    return [_customer(c) for c in customers[:30]]


# --- Pharmacist confirmation -------------------------------------------------


class ApprovalLineIn(Schema):
    key: str
    unit_id: int
    qty: int = Field(gt=0)
    dosage_text: str = ""


class ApprovalIn(Schema):
    pharmacist_id: int
    pin: str
    client_uuid: UUID
    lines: list[ApprovalLineIn]


@router.post("/approvals/dispense")
def approve_dispense(request, data: ApprovalIn):
    units = ProductUnit.objects.select_related("product").in_bulk([line.unit_id for line in data.lines])
    lines = [
        line for line in data.lines
        if line.unit_id in units and units[line.unit_id].product.needs_pharmacist
    ]
    if not lines:
        raise HttpError(400, "ไม่มีรายการที่ต้องให้เภสัชกรยืนยัน")
    detail = ", ".join(f"{units[line.unit_id].product.display_name} x{line.qty}" for line in lines)
    pharmacist = verify_pin(
        pharmacist_id=data.pharmacist_id,
        pin=data.pin,
        action=PinAttempt.Action.DISPENSE,
        requested_by=request.user,
        detail=detail,
        terminal=client_ip(request),
    )
    return {
        "pharmacist_id": pharmacist.pk,
        "pharmacist_name": pharmacist.label_name,
        "tokens": {
            line.key: sign_dispense(pharmacist, data.client_uuid, line.unit_id, line.qty, line.dosage_text)
            for line in lines
        },
    }


# --- Sales -------------------------------------------------------------------


class CheckoutLineIn(Schema):
    unit_id: int
    qty: int = Field(gt=0)
    dosage_text: str = ""
    approval: str | None = None


class CheckoutIn(Schema):
    client_uuid: UUID
    payment_method: str
    lines: list[CheckoutLineIn]
    price_level: int = 1
    customer_id: int | None = None
    buyer_name: str = ""
    cash_received: Decimal | None = None
    is_prescription: bool = False
    rx_prescriber: str = ""
    rx_prescriber_license: str = ""
    rx_facility: str = ""
    rx_date: date | None = None


class AllocationOut(Schema):
    lot_no: str
    expiry_date: date
    qty: int


class SaleItemOut(Schema):
    id: int
    description: str
    unit_name: str
    qty: int
    base_qty: int
    unit_price: Decimal
    line_total: Decimal
    category: str
    dosage_text: str
    confirmed_by: str | None
    allocations: list[AllocationOut]


class SaleOut(Schema):
    id: int
    number: str
    created_at: datetime
    cashier: str
    buyer: str
    price_level: int
    total: Decimal
    payment_method: str
    cash_received: Decimal | None
    change: Decimal | None
    status: str
    void_reason: str
    items: list[SaleItemOut]


def sale_payload(sale: Sale) -> dict:
    items = sale.items.select_related("confirmed_by").prefetch_related("allocations__lot")
    return {
        "id": sale.pk,
        "number": sale.number,
        "created_at": sale.created_at,
        "cashier": sale.cashier.label_name,
        "buyer": sale.buyer_display,
        "price_level": sale.price_level_id,
        "total": sale.total,
        "payment_method": sale.payment_method,
        "cash_received": sale.cash_received,
        "change": sale.change,
        "status": sale.status,
        "void_reason": sale.void_reason,
        "items": [
            {
                "id": item.pk,
                "description": item.description,
                "unit_name": item.unit_name,
                "qty": item.qty,
                "base_qty": item.base_qty,
                "unit_price": item.unit_price,
                "line_total": item.line_total,
                "category": item.category,
                "dosage_text": item.dosage_text,
                "confirmed_by": item.confirmed_by.label_name if item.confirmed_by else None,
                "allocations": [
                    {"lot_no": a.lot.lot_no, "expiry_date": a.lot.expiry_date, "qty": a.qty}
                    for a in item.allocations.all()
                ],
            }
            for item in items
        ],
    }


@router.post("/sales", response=SaleOut)
def create_sale(request, data: CheckoutIn):
    req = CheckoutRequest(
        client_uuid=data.client_uuid,
        payment_method=data.payment_method,
        lines=[CartLine(l.unit_id, l.qty, l.dosage_text, l.approval) for l in data.lines],
        price_level=data.price_level,
        customer_id=data.customer_id,
        buyer_name=data.buyer_name,
        cash_received=data.cash_received,
        is_prescription=data.is_prescription,
        rx_prescriber=data.rx_prescriber,
        rx_prescriber_license=data.rx_prescriber_license,
        rx_facility=data.rx_facility,
        rx_date=data.rx_date,
    )
    return sale_payload(checkout(req, request.user))


class SaleRowOut(Schema):
    id: int
    number: str
    created_at: datetime
    buyer: str
    total: Decimal
    payment_method: str
    status: str
    item_count: int


@router.get("/sales", response=list[SaleRowOut])
def list_sales(request, day: date | None = None):
    day = day or timezone.localdate()
    sales = (
        Sale.objects.filter(created_at__date=day)
        .select_related("customer")
        .annotate(item_count=Count("items"))
        .order_by("-created_at")
    )
    return [
        {
            "id": s.pk,
            "number": s.number,
            "created_at": s.created_at,
            "buyer": s.buyer_display,
            "total": s.total,
            "payment_method": s.payment_method,
            "status": s.status,
            "item_count": s.item_count,
        }
        for s in sales
    ]


@router.get("/sales/summary")
def sales_summary(request, day: date | None = None):
    return daily_summary(day or timezone.localdate())


@router.get("/sales/{sale_id}", response=SaleOut)
def get_sale(request, sale_id: int):
    return sale_payload(get_object_or_404(Sale, pk=sale_id))


class VoidIn(Schema):
    pharmacist_id: int
    pin: str
    reason: str


@router.post("/sales/{sale_id}/void", response=SaleOut)
def void(request, sale_id: int, data: VoidIn):
    sale = get_object_or_404(Sale, pk=sale_id)
    if sale.status == Sale.Status.VOIDED:
        raise HttpError(400, "บิลนี้ถูกยกเลิกไปแล้ว")
    if not data.reason.strip():
        raise HttpError(400, "ต้องระบุเหตุผลที่ยกเลิก")
    pharmacist = verify_pin(
        pharmacist_id=data.pharmacist_id,
        pin=data.pin,
        action=PinAttempt.Action.VOID,
        requested_by=request.user,
        detail=f"ยกเลิกบิล {sale.number}: {data.reason.strip()}",
        terminal=client_ip(request),
    )
    return sale_payload(void_sale(sale, pharmacist, data.reason))


# --- Held bills --------------------------------------------------------------


class HeldBillIn(Schema):
    label: str = ""
    payload: dict


class HeldBillOut(Schema):
    id: int
    created_at: datetime
    created_by: str
    label: str
    payload: dict


def _held(bill: HeldBill) -> dict:
    return {
        "id": bill.pk,
        "created_at": bill.created_at,
        "created_by": bill.created_by.label_name,
        "label": bill.label,
        "payload": bill.payload,
    }


@router.get("/held-bills", response=list[HeldBillOut])
def list_held_bills(request):
    return [_held(b) for b in HeldBill.objects.select_related("created_by")]


@router.post("/held-bills", response=HeldBillOut)
def hold_bill(request, data: HeldBillIn):
    return _held(HeldBill.objects.create(created_by=request.user, label=data.label[:200], payload=data.payload))


@router.delete("/held-bills/{bill_id}")
def delete_held_bill(request, bill_id: int):
    get_object_or_404(HeldBill, pk=bill_id).delete()
    return {"ok": True}
