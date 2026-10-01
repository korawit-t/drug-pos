import json
from datetime import date, datetime
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Prefetch, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Field, File, Form, Router, Schema, UploadedFile
from ninja.errors import HttpError

from accounts.models import PinAttempt
from accounts.services import client_ip, verify_pin

from .importer import (
    COLUMNS,
    FIELD_INFO,
    FileFormatError,
    import_rows,
    inspect_file,
    read_rows,
    template_workbook,
)
from .models import Allergen, Lot, Product, ProductUnit, Purchase, StockCount, Supplier
from .allergy import AllergyIndex
from .classify import suggest_category
from .services import (
    ProductData,
    PurchaseData,
    PurchaseLine,
    StockCountData,
    StockCountLine,
    UnitData,
    countable_lots,
    delete_count_draft,
    delete_draft,
    expired_lots,
    last_costs,
    save_product,
    save_purchase,
    save_stock_count,
)

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


# --- Importing the drug master ----------------------------------------------

MAX_UPLOAD = 10 * 1024 * 1024
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
COLUMN_LABELS = {field_name: names[0] for field_name, names in COLUMNS.items()}


class ImportIssueOut(Schema):
    row: int
    message: str


class ImportResultOut(Schema):
    rows: int
    products_created: int
    products_updated: int
    units_created: int
    units_updated: int
    stock_lines: int
    stock_base_qty: int
    default_category_rows: int
    committed: bool
    columns: list[str]  # หัวตารางที่ระบบอ่านออก (ชื่อไทยมาตรฐาน)
    errors: list[ImportIssueOut]
    warnings: list[ImportIssueOut]
    error_count: int
    warning_count: int


class FieldOut(Schema):
    name: str
    label: str
    required: bool
    help: str


class PreviewOut(Schema):
    header_row: int
    headers: list[str]
    guess: dict[str, int]
    sample: list[list[str]]
    data_rows: int
    notes: list[ImportIssueOut]
    fields: list[FieldOut]


@router.post("/import/inspect", response=PreviewOut)
def import_inspect(request, file: UploadedFile = File(...), header_row: int | None = Form(None)):
    """
    เปิดดูไฟล์ก่อนนำเข้า: หัวตารางของไฟล์เอง สิ่งที่ระบบเดาว่าแต่ละคอลัมน์คืออะไร และตัวอย่างแถวจริง
    ไฟล์จากโปรแกรมไหนก็เปิดได้ ถึงจะเดาไม่ออกสักคอลัมน์ก็ตาม — คนเป็นคนจับคู่เอง
    """
    if not request.user.is_staff:
        raise HttpError(403, "นำเข้าข้อมูลได้เฉพาะผู้ดูแลร้าน")
    if file.size > MAX_UPLOAD:
        raise HttpError(400, "ไฟล์ใหญ่เกิน 10 MB")
    try:
        preview = inspect_file(file.read(), file.name, header_row=header_row)
    except FileFormatError as exc:
        raise HttpError(400, exc.message)
    return {
        **vars(preview),
        "notes": [vars(note) for note in preview.notes],
        "fields": [
            {"name": name, "label": label, "required": required, "help": help_text}
            for name, label, required, help_text in FIELD_INFO
        ],
    }


@router.get("/import/template")
def import_template(request):
    """ไฟล์ตัวอย่างสำหรับกรอกข้อมูลยา"""
    response = HttpResponse(template_workbook(), content_type=XLSX_TYPE)
    response["Content-Disposition"] = 'attachment; filename="drugpos-import-template.xlsx"'
    return response


@router.post("/import/products", response=ImportResultOut)
def import_products(
    request,
    file: UploadedFile = File(...),
    with_stock: bool = Form(False),
    commit: bool = Form(False),
    default_category: str = Form(""),
    mapping: str = Form(""),  # JSON {field: column index} ที่คนเลือกเอง — ว่าง = ใช้ที่ระบบเดา
    header_row: int | None = Form(None),
):
    """ตรวจไฟล์ (commit=false) หรือ นำเข้าจริง (commit=true) — ถ้ามีข้อผิดพลาดจะไม่เขียนอะไรเลย"""
    if not request.user.is_staff:
        raise HttpError(403, "นำเข้าข้อมูลได้เฉพาะผู้ดูแลร้าน")
    if file.size > MAX_UPLOAD:
        raise HttpError(400, "ไฟล์ใหญ่เกิน 10 MB")
    if default_category and default_category not in Product.Category.values:
        raise HttpError(400, "ประเภทเริ่มต้นไม่ถูกต้อง")
    chosen = None
    if mapping.strip():
        try:
            chosen = {str(name): int(index) for name, index in json.loads(mapping).items() if index is not None}
        except (ValueError, TypeError, AttributeError):
            raise HttpError(400, "การจับคู่คอลัมน์ไม่ถูกต้อง")
    try:
        sheet = read_rows(file.read(), file.name, mapping=chosen, header_row=header_row)
    except FileFormatError as exc:
        raise HttpError(400, exc.message)
    result = import_rows(
        sheet.rows,
        with_stock=with_stock,
        user=request.user,
        commit=commit,
        source=file.name,
        default_category=default_category or None,
    )
    warnings = sheet.notes + result.warnings
    return {
        **vars(result),
        "columns": [COLUMN_LABELS.get(name, name) for name in sheet.columns],
        "errors": [vars(issue) for issue in result.errors[:50]],
        "warnings": [vars(issue) for issue in warnings[:50]],
        "error_count": len(result.errors),
        "warning_count": len(warnings),
    }


# --- Stock count / adjustment (นับสต็อก / ปรับยอด) ---------------------------


class CountUnitOut(Schema):
    name: str
    factor: int


class CountLotOut(Schema):
    id: int
    product_id: int
    product_name: str
    base_unit: str
    storage_location: str
    lot_no: str
    expiry_date: date
    qty: int  # ยอดในระบบตอนนี้
    expired: bool
    units: list[CountUnitOut]  # หน่วยใหญ่ไว้ให้นับเป็นกล่อง/แผง


def count_lot_payload(lot: Lot, today: date) -> dict:
    product = lot.product
    return {
        "id": lot.pk,
        "product_id": product.pk,
        "product_name": product.display_name,
        "base_unit": product.base_unit,
        "storage_location": product.storage_location,
        "lot_no": lot.lot_no,
        "expiry_date": lot.expiry_date,
        "qty": lot.qty_on_hand,
        "expired": lot.expiry_date < today,
        "units": [
            {"name": unit.name, "factor": unit.factor}
            for unit in sorted(product.units.all(), key=lambda u: u.factor)
            if unit.factor > 1
        ],
    }


def _with_product(lots):
    return lots.select_related("product").prefetch_related("product__units")


@router.get("/stock/lots", response=list[CountLotOut])
def list_lots(request, product_id: int | None = None, ids: str = ""):
    """
    lot ที่อยู่บนชั้น (รวมของหมดอายุ) สำหรับหน้านับสต็อก
    product_id: ทุก lot ที่ยังมีของของยาตัวนั้น · ids: lot ที่ระบุ (ใช้ดึงยอดล่าสุด แม้ยอดจะเหลือ 0)
    """
    today = timezone.localdate()
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    if id_list:
        lots = Lot.objects.filter(pk__in=id_list[:200]).order_by("expiry_date", "id")
    elif product_id:
        lots = countable_lots(get_object_or_404(Product, pk=product_id))
    else:
        return []
    return [count_lot_payload(lot, today) for lot in _with_product(lots)]


@router.get("/stock/lots/expired", response=list[CountLotOut])
def list_expired_lots(request):
    today = timezone.localdate()
    return [count_lot_payload(lot, today) for lot in _with_product(expired_lots(today))[:200]]


class StockCountItemOut(Schema):
    id: int
    lot: CountLotOut
    system_qty: int
    counted_qty: int | None
    difference: int | None
    reason: str
    reason_label: str
    note: str


class StockCountOut(Schema):
    id: int
    status: str
    counted_date: date
    note: str
    created_by: str
    posted_by: str
    approved_by: str
    posted_at: datetime | None
    items: list[StockCountItemOut]


class StockCountRowOut(Schema):
    id: int
    status: str
    counted_date: date
    note: str
    item_count: int
    diff_count: int
    created_by: str


def stock_count_payload(count: StockCount) -> dict:
    today = timezone.localdate()
    items = count.items.select_related("lot__product").prefetch_related("lot__product__units").order_by("id")
    return {
        "id": count.pk,
        "status": count.status,
        "counted_date": count.counted_date,
        "note": count.note,
        "created_by": _name(count.created_by),
        "posted_by": _name(count.posted_by),
        "approved_by": _name(count.approved_by),
        "posted_at": count.posted_at,
        "items": [
            {
                "id": item.pk,
                "lot": count_lot_payload(item.lot, today),
                "system_qty": item.system_qty,
                "counted_qty": item.counted_qty,
                "difference": item.difference,
                "reason": item.reason,
                "reason_label": item.get_reason_display() if item.reason else "",
                "note": item.note,
            }
            for item in items
        ],
    }


class StockCountLineIn(Schema):
    lot_id: int
    system_qty: int = Field(ge=0)
    counted_qty: int | None = Field(default=None, ge=0)
    reason: str = ""
    note: str = ""


class StockCountIn(Schema):
    counted_date: date
    note: str = ""
    lines: list[StockCountLineIn] = []
    post: bool = False  # true: ปรับยอดเข้าสต็อกด้วย (ต้องมี PIN เภสัชกร)
    pharmacist_id: int | None = None
    pin: str = ""


def _count_data(data: StockCountIn) -> StockCountData:
    return StockCountData(
        counted_date=data.counted_date,
        note=data.note,
        lines=[StockCountLine(l.lot_id, l.system_qty, l.counted_qty, l.reason, l.note) for l in data.lines],
    )


def _approval(request, data: StockCountIn):
    """ปรับยอดต้องผ่าน PIN เภสัชกรเสมอ — เก็บลงประวัติการใส่ PIN เหมือนการยกเลิกบิล"""
    if not data.post:
        return None
    if not data.pharmacist_id:
        raise HttpError(400, "เลือกเภสัชกรผู้อนุมัติก่อน")
    differences = sum(1 for l in data.lines if l.counted_qty is not None and l.counted_qty != l.system_qty)
    return verify_pin(
        pharmacist_id=data.pharmacist_id,
        pin=data.pin,
        action=PinAttempt.Action.ADJUST,
        requested_by=request.user,
        detail=f"ปรับยอดสต็อก นับวันที่ {data.counted_date} · {len(data.lines)} lot · ยอดไม่ตรง {differences}",
        terminal=client_ip(request),
    )


@router.get("/stock-counts", response=list[StockCountRowOut])
def list_stock_counts(request, limit: int = 30):
    differs = ~Q(items__counted_qty=F("items__system_qty"))
    counts = (
        StockCount.objects.select_related("created_by")
        .annotate(item_count=Count("items"), diff_count=Count("items", filter=differs))
        .order_by("status", "-counted_date", "-id")[: min(limit, 100)]
    )
    return [
        {
            "id": c.pk,
            "status": c.status,
            "counted_date": c.counted_date,
            "note": c.note,
            "item_count": c.item_count,
            "diff_count": c.diff_count,
            "created_by": _name(c.created_by),
        }
        for c in counts
    ]


@router.get("/stock-counts/{count_id}", response=StockCountOut)
def get_stock_count(request, count_id: int):
    return stock_count_payload(get_object_or_404(StockCount, pk=count_id))


@router.post("/stock-counts", response=StockCountOut)
def create_stock_count(request, data: StockCountIn):
    pharmacist = _approval(request, data)
    count = save_stock_count(_count_data(data), request.user, post=data.post, approved_by=pharmacist)
    return stock_count_payload(count)


@router.put("/stock-counts/{count_id}", response=StockCountOut)
def update_stock_count(request, count_id: int, data: StockCountIn):
    count = get_object_or_404(StockCount, pk=count_id)
    pharmacist = _approval(request, data)
    saved = save_stock_count(_count_data(data), request.user, count=count, post=data.post, approved_by=pharmacist)
    return stock_count_payload(saved)


@router.delete("/stock-counts/{count_id}")
def remove_count_draft(request, count_id: int):
    delete_count_draft(get_object_or_404(StockCount, pk=count_id))
    return {"ok": True}


# --- เพิ่ม/แก้ไขข้อมูลยาทีละรายการ (หน้า "นำเข้าข้อมูล" → ทีละรายการ) ------------


def _require_staff(request):
    if not request.user.is_staff:
        raise HttpError(403, "แก้ไขข้อมูลยาได้เฉพาะผู้ดูแลร้าน")


class ManageUnitIn(Schema):
    id: int | None = None
    name: str
    factor: int = Field(default=1, ge=1)
    barcode: str = ""
    is_default: bool = False
    prices: list[Decimal | None] = []  # ราคาดิบ ช่องว่าง = ยังไม่ตั้ง (ไม่ใช่ 0)


class ManageProductIn(Schema):
    code: str = ""
    trade_name: str
    generic_name: str = ""
    strength: str = ""
    dosage_form: str = ""
    category: str
    base_unit: str
    registration_no: str = ""
    in_ky11_list: bool = False
    in_ky13_list: bool = False
    default_dosage: str = ""
    label_warning: str = ""
    storage_location: str = ""
    is_active: bool = True
    allergen_ids: list[int] = []
    units: list[ManageUnitIn] = []


class ManageUnitOut(Schema):
    id: int
    name: str
    factor: int
    barcode: str
    is_default: bool
    prices: list[Decimal | None]


class SuggestionOut(Schema):
    category: str
    label: str
    term: str  # คำในชื่อยาที่ทำให้เสนอแบบนี้ — แสดงให้เภสัชตัดสินใจได้


def _suggestion(product: Product) -> dict | None:
    found = suggest_category(product.trade_name, product.generic_name)
    if found is None:
        return None
    category, term = found
    return {"category": category, "label": dict(Product.Category.choices)[category], "term": term}


class ManageProductOut(Schema):
    id: int
    code: str
    trade_name: str
    generic_name: str
    strength: str
    dosage_form: str
    category: str
    category_label: str
    base_unit: str
    registration_no: str
    in_ky11_list: bool
    in_ky13_list: bool
    default_dosage: str
    label_warning: str
    storage_location: str
    is_active: bool
    allergen_ids: list[int]
    matched_allergens: str  # กลุ่มยาที่ระบบจับคู่ได้เองจากชื่อ
    units: list[ManageUnitOut]
    on_hand: int
    needs_review: bool
    suggestion: SuggestionOut | None


class ManageRowOut(Schema):
    id: int
    code: str
    display_name: str
    generic_name: str
    category_label: str
    base_unit: str
    unit_count: int
    on_hand: int
    is_active: bool
    missing: list[str]  # review / barcode / generic / unit
    suggestion: SuggestionOut | None
    units: list[ManageUnitOut]  # ใช้ยิงบาร์โค้ดจากหน้ารายการได้เลย


# งานที่ยังค้างของยาแต่ละตัว — ไฟล์จากโปรแกรมเดิมมักให้มาไม่ครบ
GAPS = {
    "review": ("ยังไม่ได้ตรวจประเภทยา", "ระบบเดาประเภทให้ตอนนำเข้า ต้องมีเภสัชกรยืนยัน"),
    "barcode": ("ยังมีหน่วยขายที่ไม่มีบาร์โค้ด", "หน่วยที่ไม่มีบาร์โค้ดจะสแกนขายไม่ได้ ต้องพิมพ์ชื่อหา"),
    "generic": ("ยังไม่มีชื่อสามัญ", "แจ้งเตือนแพ้ยาจะจับคู่ไม่ได้"),
    "unit": ("ขายได้หน่วยเดียว", "ไม่มีหน่วยย่อย เช่น ซื้อมาเป็นกล่องแต่ขายเป็นเม็ดไม่ได้"),
}


def _gaps_of(product: Product) -> list[str]:
    units = list(product.units.all())
    gaps = []
    if product.needs_review:
        gaps.append("review")
    if any(not unit.barcode for unit in units):
        gaps.append("barcode")
    if not product.generic_name.strip():
        gaps.append("generic")
    if len(units) < 2 and all(unit.factor == 1 for unit in units):
        gaps.append("unit")
    return gaps


def manage_payload(product: Product) -> dict:
    index = AllergyIndex()
    groups = index.product_groups(product)
    return {
        "id": product.pk,
        "code": product.code,
        "trade_name": product.trade_name,
        "generic_name": product.generic_name,
        "strength": product.strength,
        "dosage_form": product.dosage_form,
        "category": product.category,
        "category_label": product.get_category_display(),
        "base_unit": product.base_unit,
        "registration_no": product.registration_no,
        "in_ky11_list": product.in_ky11_list,
        "in_ky13_list": product.in_ky13_list,
        "default_dosage": product.default_dosage,
        "label_warning": product.label_warning,
        "storage_location": product.storage_location,
        "is_active": product.is_active,
        "allergen_ids": [a.pk for a in product.allergens.all()],
        "matched_allergens": index.describe(groups) if groups else "",
        "units": [
            {
                "id": unit.pk,
                "name": unit.name,
                "factor": unit.factor,
                "barcode": unit.barcode,
                "is_default": unit.is_default,
                "prices": [getattr(unit, f"price{level}") for level in range(1, 6)],
            }
            for unit in sorted(product.units.all(), key=lambda u: u.factor)
        ],
        "on_hand": sum(lot.qty_on_hand for lot in product.lots.all()),
        "needs_review": product.needs_review,
        "suggestion": _suggestion(product),
    }


def _product_data(data: ManageProductIn) -> ProductData:
    return ProductData(
        trade_name=data.trade_name,
        base_unit=data.base_unit,
        category=data.category,
        code=data.code,
        generic_name=data.generic_name,
        strength=data.strength,
        dosage_form=data.dosage_form,
        registration_no=data.registration_no,
        in_ky11_list=data.in_ky11_list,
        in_ky13_list=data.in_ky13_list,
        default_dosage=data.default_dosage,
        label_warning=data.label_warning,
        storage_location=data.storage_location,
        is_active=data.is_active,
        allergen_ids=data.allergen_ids,
        units=[UnitData(u.name, u.factor, u.barcode, u.is_default, list(u.prices), u.id) for u in data.units],
    )


def _manage_rows(q: str = "", missing: str = ""):
    products = Product.objects.prefetch_related("units", "lots").order_by("trade_name")
    if q := q.strip():
        products = products.filter(
            Q(trade_name__icontains=q) | Q(generic_name__icontains=q) | Q(code__icontains=q)
            | Q(units__barcode__startswith=q)
        ).distinct()
    rows = [(p, _gaps_of(p)) for p in products]
    if missing in GAPS:
        rows = [(p, gaps) for p, gaps in rows if missing in gaps]
    return rows


@router.get("/manage/products", response=list[ManageRowOut])
def list_manage_products(request, q: str = "", missing: str = "", limit: int = 50):
    _require_staff(request)
    return [
        {
            "id": p.pk,
            "code": p.code,
            "display_name": p.display_name,
            "generic_name": p.generic_name,
            "category_label": p.get_category_display(),
            "base_unit": p.base_unit,
            "unit_count": len(p.units.all()),
            "on_hand": sum(lot.qty_on_hand for lot in p.lots.all()),
            "is_active": p.is_active,
            "missing": gaps,
            "suggestion": _suggestion(p) if "review" in gaps else None,
            "units": [
                {
                    "id": unit.pk, "name": unit.name, "factor": unit.factor, "barcode": unit.barcode,
                    "is_default": unit.is_default,
                    "prices": [getattr(unit, f"price{level}") for level in range(1, 6)],
                }
                for unit in sorted(p.units.all(), key=lambda u: u.factor)
            ],
        }
        for p, gaps in _manage_rows(q, missing)[: min(limit, 200)]
    ]


class GapOut(Schema):
    key: str
    label: str
    why: str
    count: int


@router.get("/manage/gaps", response=list[GapOut])
def list_manage_gaps(request):
    """สรุปว่ายังมียากี่ตัวที่ข้อมูลไม่ครบในแต่ละเรื่อง — ใช้เป็นรายการงานหลังนำเข้าไฟล์"""
    _require_staff(request)
    counts = dict.fromkeys(GAPS, 0)
    for _, gaps in _manage_rows():
        for gap in gaps:
            counts[gap] += 1
    return [{"key": key, "label": label, "why": why, "count": counts[key]} for key, (label, why) in GAPS.items()]


class CategoryIn(Schema):
    category: str


@router.put("/manage/products/{product_id}/category", response=ManageProductOut)
def set_product_category(request, product_id: int, data: CategoryIn):
    """ยืนยันประเภทยาทีละตัวจากหน้าตรวจทาน — ปลดธง "ยังไม่ได้ตรวจทาน" ด้วย"""
    _require_staff(request)
    if data.category not in Product.Category.values:
        raise HttpError(400, "ประเภทยาไม่ถูกต้อง")
    product = get_object_or_404(Product, pk=product_id)
    product.category = data.category
    product.needs_review = False
    product.save(update_fields=["category", "needs_review"])
    return manage_payload(product)


class BarcodeIn(Schema):
    barcode: str


@router.put("/manage/units/{unit_id}/barcode", response=ManageProductOut)
def set_unit_barcode(request, unit_id: int, data: BarcodeIn):
    """ตั้งบาร์โค้ดทีละหน่วยด้วยเครื่องสแกน — ไล่ยิงทีละตัวได้โดยไม่ต้องเปิดฟอร์มเต็ม"""
    _require_staff(request)
    unit = get_object_or_404(ProductUnit.objects.select_related("product"), pk=unit_id)
    barcode = data.barcode.strip()[:50]
    if barcode:
        clash = ProductUnit.objects.filter(barcode=barcode).exclude(pk=unit.pk).select_related("product").first()
        if clash is not None:
            raise HttpError(400, f"บาร์โค้ด {barcode} ใช้อยู่กับ {clash.product.display_name} ({clash.name}) แล้ว")
    unit.barcode = barcode
    unit.save(update_fields=["barcode"])
    return manage_payload(unit.product)


@router.get("/manage/products/{product_id}", response=ManageProductOut)
def get_manage_product(request, product_id: int):
    _require_staff(request)
    return manage_payload(get_object_or_404(Product, pk=product_id))


@router.post("/manage/products", response=ManageProductOut)
def create_manage_product(request, data: ManageProductIn):
    _require_staff(request)
    return manage_payload(save_product(_product_data(data)))


@router.put("/manage/products/{product_id}", response=ManageProductOut)
def update_manage_product(request, product_id: int, data: ManageProductIn):
    _require_staff(request)
    product = get_object_or_404(Product, pk=product_id)
    return manage_payload(save_product(_product_data(data), product=product))
