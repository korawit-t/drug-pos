from datetime import date, datetime
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Prefetch, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Field, Router, Schema

from .models import Allergen, Lot, Product, ProductUnit, Purchase, Supplier
from .services import PurchaseData, PurchaseLine, delete_draft, last_costs, save_purchase

router = Router(tags=["products"])


class UnitOut(Schema):
    id: int
    name: str
    factor: int
    barcode: str
    is_default: bool
    prices: list[Decimal]  # effective price at levels 1–5 (empty levels fall back to level 1)


class LotOut(Schema):
    lot_no: str
    expiry_date: date
    qty: int


class ProductOut(Schema):
    id: int
    display_name: str
    trade_name: str
    generic_name: str
    strength: str
    dosage_form: str
    category: str
    category_label: str
    base_unit: str
    needs_pharmacist: bool
    needs_prescription: bool
    needs_buyer_name: bool
    in_ky13_list: bool
    default_dosage: str
    label_warning: str
    storage_location: str
    available: int  # base units in lots that haven't expired
    expired: int  # base units still on the shelf but past expiry
    lots: list[LotOut]  # sellable lots, FEFO order
    units: list[UnitOut]
    matched_unit_id: int | None = None


def _products():
    return Product.objects.filter(is_active=True).prefetch_related(
        "units", Prefetch("lots", queryset=Lot.objects.filter(qty_on_hand__gt=0).order_by("expiry_date", "id"))
    )


def product_payload(product: Product, today: date, matched_unit_id: int | None = None) -> dict:
    lots = list(product.lots.all())
    sellable = [lot for lot in lots if lot.expiry_date >= today]
    return {
        "id": product.pk,
        "display_name": product.display_name,
        "trade_name": product.trade_name,
        "generic_name": product.generic_name,
        "strength": product.strength,
        "dosage_form": product.dosage_form,
        "category": product.category,
        "category_label": product.get_category_display(),
        "base_unit": product.base_unit,
        "needs_pharmacist": product.needs_pharmacist,
        "needs_prescription": product.needs_prescription,
        "needs_buyer_name": product.needs_buyer_name,
        "in_ky13_list": product.in_ky13_list,
        "default_dosage": product.default_dosage,
        "label_warning": product.label_warning,
        "storage_location": product.storage_location,
        "available": sum(lot.qty_on_hand for lot in sellable),
        "expired": sum(lot.qty_on_hand for lot in lots if lot.expiry_date < today),
        "lots": [{"lot_no": lot.lot_no, "expiry_date": lot.expiry_date, "qty": lot.qty_on_hand} for lot in sellable],
        "units": [
            {
                "id": unit.pk,
                "name": unit.name,
                "factor": unit.factor,
                "barcode": unit.barcode,
                "is_default": unit.is_default,
                "prices": [unit.price_for(level) for level in range(1, 6)],
            }
            for unit in sorted(product.units.all(), key=lambda u: u.factor)
        ],
        "matched_unit_id": matched_unit_id,
    }


@router.get("/products/search", response=list[ProductOut])
def search_products(request, q: str = "", limit: int = 20):
    """A scanned barcode matches one unit exactly; otherwise search trade/generic names."""
    q = q.strip()
    if not q:
        return []
    today = timezone.localdate()
    unit = ProductUnit.objects.filter(barcode=q, product__is_active=True).first()
    if unit:
        return [product_payload(_products().get(pk=unit.product_id), today, matched_unit_id=unit.pk)]
    products = (
        _products()
        .filter(Q(trade_name__icontains=q) | Q(generic_name__icontains=q) | Q(units__barcode__startswith=q))
        .distinct()[: min(limit, 50)]
    )
    return [product_payload(p, today) for p in products]


@router.get("/products", response=list[ProductOut])
def products_by_id(request, ids: str):
    """Fresh prices and stock for products already in a cart (used when resuming a held bill)."""
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    today = timezone.localdate()
    return [product_payload(p, today) for p in _products().filter(pk__in=id_list)]


class AllergenOut(Schema):
    id: int
    name: str


@router.get("/allergens", response=list[AllergenOut])
def list_allergens(request):
    return [{"id": a.pk, "name": a.name} for a in Allergen.objects.all()]


# --- Receiving (รับยาเข้า) ---------------------------------------------------


class SupplierOut(Schema):
    id: int
    name: str


@router.get("/suppliers", response=list[SupplierOut])
def list_suppliers(request):
    return [{"id": s.pk, "name": s.name} for s in Supplier.objects.all()]


class PurchaseLineIn(Schema):
    unit_id: int
    qty: int = Field(gt=0)
    lot_no: str = ""
    expiry_date: date | None = None
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)


class PurchaseIn(Schema):
    received_date: date
    is_opening_balance: bool = False
    supplier_id: int | None = None
    invoice_no: str = ""
    invoice_date: date | None = None
    note: str = ""
    lines: list[PurchaseLineIn] = []
    post: bool = False  # true: also post to stock (all or nothing)


class PurchaseItemOut(Schema):
    id: int
    unit_id: int
    product: ProductOut
    qty: int
    lot_no: str
    expiry_date: date | None
    unit_cost: Decimal | None
    line_total: Decimal


class PurchaseOut(Schema):
    id: int
    status: str
    is_opening_balance: bool
    supplier_id: int | None
    supplier_name: str
    invoice_no: str
    invoice_date: date | None
    received_date: date
    note: str
    created_by: str
    posted_by: str
    posted_at: datetime | None
    total_cost: Decimal
    items: list[PurchaseItemOut]


class PurchaseRowOut(Schema):
    id: int
    status: str
    is_opening_balance: bool
    supplier_name: str
    invoice_no: str
    received_date: date
    item_count: int
    total_cost: Decimal
    created_by: str


def _name(user) -> str:
    return user.label_name if user else ""


def purchase_payload(purchase: Purchase) -> dict:
    today = timezone.localdate()
    items = list(purchase.items.select_related("unit").order_by("id"))
    products = {p.pk: p for p in _products_any().filter(pk__in={item.unit.product_id for item in items})}
    lines = [
        {
            "id": item.pk,
            "unit_id": item.unit_id,
            "product": product_payload(products[item.unit.product_id], today),
            "qty": item.qty,
            "lot_no": item.lot_no,
            "expiry_date": item.expiry_date,
            "unit_cost": item.unit_cost,
            "line_total": (item.unit_cost or Decimal("0")) * item.qty,
        }
        for item in items
    ]
    return {
        "id": purchase.pk,
        "status": purchase.status,
        "is_opening_balance": purchase.is_opening_balance,
        "supplier_id": purchase.supplier_id,
        "supplier_name": purchase.supplier.name if purchase.supplier else "",
        "invoice_no": purchase.invoice_no,
        "invoice_date": purchase.invoice_date,
        "received_date": purchase.received_date,
        "note": purchase.note,
        "created_by": _name(purchase.created_by),
        "posted_by": _name(purchase.posted_by),
        "posted_at": purchase.posted_at,
        "total_cost": sum((line["line_total"] for line in lines), Decimal("0")),
        "items": lines,
    }


def _products_any():
    """Like _products() but keeps inactive products, so old receipts still open."""
    return Product.objects.prefetch_related(
        "units", Prefetch("lots", queryset=Lot.objects.filter(qty_on_hand__gt=0).order_by("expiry_date", "id"))
    )


def _purchase_data(data: PurchaseIn) -> PurchaseData:
    return PurchaseData(
        received_date=data.received_date,
        is_opening_balance=data.is_opening_balance,
        supplier_id=data.supplier_id,
        invoice_no=data.invoice_no,
        invoice_date=data.invoice_date,
        note=data.note,
        lines=[PurchaseLine(l.unit_id, l.qty, l.lot_no, l.expiry_date, l.unit_cost) for l in data.lines],
    )


@router.get("/purchases", response=list[PurchaseRowOut])
def list_purchases(request, limit: int = 30):
    line_total = ExpressionWrapper(F("items__qty") * F("items__unit_cost"), output_field=DecimalField())
    purchases = (
        Purchase.objects.select_related("supplier", "created_by")
        .annotate(item_count=Count("items"), total_cost=Sum(line_total))
        .order_by("status", "-received_date", "-id")[: min(limit, 100)]
    )
    return [
        {
            "id": p.pk,
            "status": p.status,
            "is_opening_balance": p.is_opening_balance,
            "supplier_name": p.supplier.name if p.supplier else "",
            "invoice_no": p.invoice_no,
            "received_date": p.received_date,
            "item_count": p.item_count,
            "total_cost": p.total_cost or Decimal("0"),
            "created_by": _name(p.created_by),
        }
        for p in purchases
    ]


@router.get("/purchases/last-costs")
def purchase_last_costs(request, unit_ids: str):
    ids = [int(x) for x in unit_ids.split(",") if x.strip().isdigit()]
    return {str(unit_id): cost for unit_id, cost in last_costs(ids).items()}


@router.get("/purchases/{purchase_id}", response=PurchaseOut)
def get_purchase(request, purchase_id: int):
    return purchase_payload(get_object_or_404(Purchase, pk=purchase_id))


@router.post("/purchases", response=PurchaseOut)
def create_purchase(request, data: PurchaseIn):
    return purchase_payload(save_purchase(_purchase_data(data), request.user, post=data.post))


@router.put("/purchases/{purchase_id}", response=PurchaseOut)
def update_purchase(request, purchase_id: int, data: PurchaseIn):
    purchase = get_object_or_404(Purchase, pk=purchase_id)
    return purchase_payload(save_purchase(_purchase_data(data), request.user, purchase=purchase, post=data.post))


@router.delete("/purchases/{purchase_id}")
def remove_draft(request, purchase_id: int):
    delete_draft(get_object_or_404(Purchase, pk=purchase_id))
    return {"ok": True}
