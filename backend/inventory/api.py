from datetime import date
from decimal import Decimal

from django.db.models import Prefetch, Q
from django.utils import timezone
from ninja import Router, Schema

from .models import Lot, Product, ProductUnit

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
