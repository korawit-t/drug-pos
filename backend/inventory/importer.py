"""
Import the drug master (and opening stock) from the shop's own spreadsheet.

One row is one selling unit, so a drug sold by tablet, strip and box is three
rows with the same trade name. Everything is checked first and written only if
every row is good — a half-imported price list is worse than none.
"""

import csv
import io
import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from core.thai import parse_expiry, thai_date

from .models import Product, ProductUnit, Purchase, PurchaseItem
from .services import StockError, post_purchase

MAX_ROWS = 5000
HEADER_SCAN_ROWS = 15  # exports usually put a title (and sometimes a date) above the header
PRICE_FIELDS = [f"price{level}" for level in range(1, 6)]
OPENING_LOT = "ยกมา"  # stand-in when the old system exported stock without lot numbers

# Accepted spellings per column. The first one is what the template uses; the
# rest are what real exports from other shop programs actually look like.
COLUMNS = {
    "code": ["รหัสสินค้า", "รหัส", "รหัสยา", "product_code", "code"],
    "trade_name": ["ชื่อการค้า", "ชื่อยา", "ชื่อสินค้า", "ชื่อ", "รายการ", "trade_name", "name"],
    "generic_name": ["ชื่อสามัญ", "generic_name", "generic"],
    "strength": ["ความแรง", "strength"],
    "dosage_form": ["รูปแบบยา", "รูปแบบ", "dosage_form"],
    "category": ["ประเภท", "ประเภทยา", "category"],
    "base_unit": ["หน่วยเล็กสุด", "หน่วยนับ", "base_unit"],
    "unit_name": ["หน่วยขาย", "หน่วย", "unit"],
    "factor": ["จำนวนหน่วยเล็กสุดต่อหน่วยขาย", "ตัวคูณ", "factor"],
    "barcode": ["บาร์โค้ด", "barcode"],
    "is_default": ["หน่วยขายหลัก", "หน่วยหลัก", "is_default"],
    "price1": ["ราคา1", "ราคา", "ราคาขาย", "ราคาระดับ1", "ระดับ1", "price1"],
    "price2": ["ราคา2", "ราคาระดับ2", "ระดับ2", "price2"],
    "price3": ["ราคา3", "ราคาระดับ3", "ระดับ3", "price3"],
    "price4": ["ราคา4", "ราคาระดับ4", "ระดับ4", "price4"],
    "price5": ["ราคา5", "ราคาระดับ5", "ระดับ5", "price5"],
    "registration_no": ["เลขทะเบียนตำรับ", "เลขทะเบียน", "registration_no"],
    "in_ky11_list": ["ขย.11", "ต้องลงขย.11", "ky11"],
    "in_ky13_list": ["ขย.13", "ต้องรายงานขย.13", "ky13"],
    "default_dosage": ["วิธีใช้", "default_dosage"],
    "label_warning": ["คำเตือน", "label_warning"],
    "storage_location": ["ที่เก็บ", "storage_location"],
    "stock_qty": ["ยอดยกมา", "จำนวนยกมา", "คงเหลือ", "จำนวนคงเหลือ", "จำนวนเหลือ", "จำนวน", "stock_qty"],
    "lot_no": ["lot", "เลขที่lot", "lot_no"],
    "expiry": ["วันหมดอายุ", "วันที่หมดอายุ", "หมดอายุ", "expiry", "exp"],
    "unit_cost": ["ราคาทุน", "ทุน/หน่วย", "ต้นทุน", "ต้นทุน/หน่วย", "ต้นทุนต่อหน่วย", "ทุน", "unit_cost"],
}

CATEGORY_ALIASES = {
    "ทั่วไป": Product.Category.GENERAL,
    "สินค้า": Product.Category.GENERAL,
    "สามัญประจำบ้าน": Product.Category.HOUSEHOLD,
    "ยาสามัญ": Product.Category.HOUSEHOLD,
    "บรรจุเสร็จ": Product.Category.READY_PACKED,
    "อันตราย": Product.Category.DANGEROUS,
    "ควบคุมพิเศษ": Product.Category.SPECIAL_CONTROLLED,
}

TRUE_WORDS = {"ใช่", "มี", "y", "yes", "true", "1", "x", "✓", "/"}
FALSE_WORDS = {"", "ไม่", "ไม่ใช่", "n", "no", "false", "0", "-"}


def normalize(text) -> str:
    return re.sub(r"[\s_]+", "", str(text or "")).lower()


def category_of(text: str):
    key = normalize(text)
    if not key:
        return None
    for value, label in Product.Category.choices:
        if key in (normalize(label), normalize(value)):
            return value
    for alias, value in CATEGORY_ALIASES.items():
        if normalize(alias) in key:
            return value
    return "unknown"


def yes_no(value, default=False):
    key = normalize(value)
    if key in TRUE_WORDS:
        return True
    if key in FALSE_WORDS:
        return False
    return default


def as_decimal(value):
    text = str(value or "").replace(",", "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return "invalid"


def as_int(value):
    number = as_decimal(value)
    if number in (None, "invalid"):
        return number
    return int(number) if number == number.to_integral_value() else "invalid"


@dataclass
class Issue:
    row: int
    message: str


@dataclass
class ImportResult:
    rows: int = 0
    products_created: int = 0
    products_updated: int = 0
    units_created: int = 0
    units_updated: int = 0
    stock_lines: int = 0
    stock_base_qty: int = 0
    default_category_rows: int = 0  # new drugs that had no ประเภท in the file
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    committed: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors


class FileFormatError(Exception):
    """The file itself can't be read (wrong format, no header row)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# --- Reading the file --------------------------------------------------------


@dataclass
class Sheet:
    """What was read out of the file, plus anything the shop should know about how it was read."""

    rows: list[dict] = field(default_factory=list)
    notes: list[Issue] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)  # fields the header actually matched


@dataclass
class Preview:
    """
    What the file looks like before anything is imported: its own column names,
    our best guess at what each one means, and the first rows as we would read
    them. Every shop's old program names its columns differently, so the guess
    is a starting point for the person to correct, not the answer.
    """

    header_row: int  # 1-based, as the spreadsheet shows it
    headers: list[str]
    guess: dict[str, int]  # field -> column index
    sample: list[list[str]]
    data_rows: int
    notes: list[Issue] = field(default_factory=list)


# What each importable field is, for the column-matching screen to build itself.
FIELD_INFO = [
    ("code", "รหัสสินค้า", False, "รหัสจากโปรแกรมเดิม ใช้จับคู่ตอนนำเข้าซ้ำ"),
    ("trade_name", "ชื่อการค้า", True, "ชื่อที่พิมพ์บนกล่อง"),
    ("generic_name", "ชื่อสามัญ", False, "ชื่อตัวยา ใช้แจ้งเตือนแพ้ยา"),
    ("strength", "ความแรง", False, "เช่น 500 mg"),
    ("dosage_form", "รูปแบบยา", False, "เช่น เม็ด แคปซูล น้ำเชื่อม"),
    ("category", "ประเภทยา", False, "ถ้าไฟล์ไม่มี ให้เลือกประเภทเริ่มต้นด้านล่าง"),
    ("base_unit", "หน่วยเล็กสุด", False, "หน่วยที่ใช้นับสต็อก ถ้าไม่มีจะใช้หน่วยขาย"),
    ("unit_name", "หน่วยขาย", True, "หน่วยของแถวนี้ เช่น แผง"),
    ("factor", "จำนวนหน่วยเล็กสุดต่อหน่วยขาย", False, "เช่น แผงละ 10 เม็ด ใส่ 10 — ไม่มีถือว่า 1"),
    ("barcode", "บาร์โค้ด", False, "ของหน่วยขายนี้"),
    ("is_default", "หน่วยขายหลัก", False, "ใส่ ใช่ ในหน่วยที่ขายบ่อยที่สุด"),
    ("price1", "ราคา 1 (ปลีก)", True, "ราคาขายปลีก"),
    ("price2", "ราคา 2", False, "เว้นว่างหรือ 0 = ใช้ราคา 1"),
    ("price3", "ราคา 3", False, "เว้นว่างหรือ 0 = ใช้ราคา 1"),
    ("price4", "ราคา 4", False, "เว้นว่างหรือ 0 = ใช้ราคา 1"),
    ("price5", "ราคา 5", False, "เว้นว่างหรือ 0 = ใช้ราคา 1"),
    ("registration_no", "เลขทะเบียนตำรับ", False, "ใช้ในรายงาน ขย.9"),
    ("in_ky11_list", "ต้องลง ขย.11", False, "ใส่ ใช่ ถ้าต้องลงบัญชี"),
    ("in_ky13_list", "ต้องรายงาน ขย.13", False, "ใส่ ใช่ ถ้าต้องรายงาน"),
    ("default_dosage", "วิธีใช้", False, "ขึ้นบนฉลากยา"),
    ("label_warning", "คำเตือน", False, "ขึ้นบนฉลากยา"),
    ("storage_location", "ที่เก็บ", False, "เช่น ชั้น A1"),
    ("stock_qty", "ยอดยกมา", False, "จำนวนที่มีอยู่จริง นับเป็นหน่วยขายของแถวนี้"),
    ("lot_no", "เลขที่ lot", False, f"ไม่มีก็ได้ จะใช้ lot ชื่อ \"{OPENING_LOT}\""),
    ("expiry", "วันหมดอายุ", False, "ต้องมีถ้ามียอดยกมา"),
    ("unit_cost", "ราคาทุน", False, "ทุนต่อหน่วยขายของแถวนี้"),
]


def _blank(cells) -> bool:
    return not any(str(cell or "").strip() for cell in cells)


def _used_width(cells) -> int:
    """How many columns the row actually fills, ignoring trailing empties."""
    width = 0
    for index, cell in enumerate(cells):
        if str(cell or "").strip():
            width = index + 1
    return width


def _widest(table: list[list]) -> int:
    return max((_used_width(cells) for cells in table), default=0)


def _header_by_shape(table: list[list]) -> int:
    """
    When no column name is recognised, the header is the first row as wide as the
    table itself — a report's title line is one cell, the header and its data are
    the full width.
    """
    widths = Counter(_used_width(cells) for cells in table if not _blank(cells))
    if not widths:
        return 0
    # ชนะด้วยจำนวนแถวก่อน ถ้าเท่ากันเอาแถวที่กว้างกว่า
    common = max(widths.items(), key=lambda item: (item[1], item[0]))[0]
    for index, cells in enumerate(table):
        if not _blank(cells) and _used_width(cells) == common:
            return index
    return next((index for index, cells in enumerate(table) if not _blank(cells)), 0)


def _find_header(table: list[list]) -> tuple[int, dict[str, int]] | None:
    """
    Reports from other programs start with a title line (sometimes a date too),
    so the header is whichever of the first rows matches the most known columns.
    """
    best = None
    for index, cells in enumerate(table[:HEADER_SCAN_ROWS]):
        mapping = _map_header(cells)
        if "trade_name" not in mapping or len(mapping) < 2:
            continue
        if best is None or len(mapping) > len(best[1]):
            best = (index, mapping)
    return best


def _table_of(data: bytes) -> list[list]:
    table = _xlsx_table(data) if data[:2] == b"PK" else _csv_table(data)
    if not any(not _blank(cells) for cells in table):
        raise FileFormatError("ไฟล์ว่าง ไม่มีข้อมูล")
    return table


def _locate(table: list[list], header_row: int | None, *, strict: bool = True) -> tuple[int, dict[str, int]]:
    """
    Where the header is and what we think each of its columns means. A file whose
    columns we recognise nothing of is still openable (strict=False): the person
    picks the columns on screen, which is how an export from any program gets in.
    """
    if header_row is not None:
        index = header_row - 1
        if not 0 <= index < len(table):
            raise FileFormatError(f"ไม่มีแถวที่ {header_row} ในไฟล์นี้")
        return index, _map_header(table[index])
    found = _find_header(table)
    if found is not None:
        return found
    if strict:
        raise FileFormatError(
            "ไม่พบหัวตารางใน 15 แถวแรก — ต้องมีคอลัมน์ชื่อยาอย่างน้อยหนึ่งคอลัมน์ "
            "(เช่น 'ชื่อการค้า', 'ชื่อสินค้า', 'รายการ') หรือเลือกแถวหัวตารางเอง"
        )
    index = _header_by_shape(table)
    return index, _map_header(table[index])


def _body_rows(table: list[list], header_index: int, notes: list[Issue]):
    """Data rows under the header, stopping where the data stops."""
    body = table[header_index + 1 :]
    rows = []
    for offset, cells in enumerate(body):
        number = header_index + 2 + offset
        # Summary lines after a blank row are the end of the data, not more data.
        if _blank(cells):
            left = sum(1 for rest in body[offset + 1 :] if not _blank(rest))
            if left:
                notes.append(
                    Issue(number, f"หยุดอ่านที่แถวว่าง — ไม่ได้อ่านอีก {left} แถวข้างล่าง (มักเป็นบรรทัดสรุปท้ายรายงาน)")
                )
            break
        rows.append((number, cells))
        if len(rows) > MAX_ROWS:
            raise FileFormatError(f"ไฟล์มีเกิน {MAX_ROWS:,} แถว — แบ่งไฟล์ก่อนนำเข้า")
    return rows


def inspect_file(data: bytes, filename: str = "", header_row: int | None = None, sample_size: int = 8) -> Preview:
    """
    Look at the file without importing anything: its own column names, our guess
    at what they mean, and the first rows. The shop corrects the guess on screen,
    which is what lets any program's export be imported without us knowing it.
    """
    table = _table_of(data)
    header_index, guess = _locate(table, header_row, strict=False)
    notes = []
    if header_index and header_row is None:
        notes.append(Issue(header_index + 1, f"ข้าม {header_index} แถวบนสุดที่ไม่ใช่หัวตาราง"))
    body = _body_rows(table, header_index, notes)
    width = max(_widest(table), 1)
    headers = [str(cell or "").strip() for cell in table[header_index]]
    headers += [""] * (width - len(headers))
    return Preview(
        header_row=header_index + 1,
        headers=headers,
        guess=guess,
        sample=[[str(cell or "").strip() for cell in cells[:width]] for _, cells in body[:sample_size]],
        data_rows=len(body),
        notes=notes,
    )


def read_rows(data: bytes, filename: str = "", mapping: dict[str, int] | None = None, header_row: int | None = None) -> Sheet:
    """
    Rows as {field: value} dicts, with the spreadsheet row number in '_row'.
    Pass mapping to use the columns the shop picked instead of our guess.
    """
    table = _table_of(data)
    header_index, guess = _locate(table, header_row, strict=mapping is None)
    if mapping is None:
        mapping = guess
    else:
        known = {name for name, *_ in FIELD_INFO}
        width = _widest(table)  # แถวข้อมูลกว้างกว่าหัวตารางได้
        mapping = {
            name: int(index)
            for name, index in mapping.items()
            if name in known and index is not None and 0 <= int(index) < max(width, 1)
        }
    missing = [label for name, label, required, _ in FIELD_INFO if required and name not in mapping]
    if missing:
        raise FileFormatError(
            f"ยังไม่ได้บอกว่าคอลัมน์ไหนคือ {' และ '.join(missing)} — เลือกให้ครบก่อนนำเข้า"
        )

    sheet = Sheet(columns=sorted(mapping))
    if header_index and header_row is None:
        sheet.notes.append(Issue(header_index + 1, f"ข้าม {header_index} แถวบนสุดที่ไม่ใช่หัวตาราง"))
    for number, cells in _body_rows(table, header_index, sheet.notes):
        row = {field_name: cells[index] if index < len(cells) else None for field_name, index in mapping.items()}
        row["_row"] = number
        sheet.rows.append(row)
    return sheet


def _xlsx_table(data: bytes) -> list[list]:
    workbook = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    return [list(cells) for cells in workbook[workbook.sheetnames[0]].iter_rows(values_only=True)]


def _csv_table(data: bytes) -> list[list]:
    # Excel on Windows still writes Thai CSV as cp874 (TIS-620).
    for encoding in ("utf-8-sig", "cp874", "utf-8"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise FileFormatError("อ่านไฟล์ไม่ได้ — บันทึกเป็น .xlsx หรือ CSV UTF-8 แล้วลองใหม่")
    try:
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [row for row in csv.reader(io.StringIO(text), dialect)]


def _map_header(header: list) -> dict[str, int]:
    seen = {normalize(name): index for index, name in enumerate(header) if str(name or "").strip()}
    mapping = {}
    for field_name, names in COLUMNS.items():
        for name in names:
            if (index := seen.get(normalize(name))) is not None:
                mapping[field_name] = index
                break
    return mapping


# --- Applying the rows -------------------------------------------------------


class _Rollback(Exception):
    pass


def import_rows(
    rows: list[dict],
    *,
    with_stock: bool,
    user=None,
    commit: bool,
    source: str = "",
    default_category: str | None = None,
) -> ImportResult:
    """
    Dry run and the real import take the same path — the dry run just rolls the
    transaction back, so the preview is exactly what would happen.

    default_category applies only to drugs the file doesn't classify and that
    aren't in the system yet; it never re-classifies a drug already on file.
    """
    result = ImportResult(rows=len(rows))
    try:
        with transaction.atomic():
            _apply(rows, result, with_stock=with_stock, user=user, source=source, default_category=default_category)
            if not result.ok or not commit:
                raise _Rollback
            result.committed = True
    except _Rollback:
        pass
    return result


def _apply(rows, result: ImportResult, *, with_stock: bool, user, source: str, default_category=None):
    products: dict[tuple[str, str], Product] = {}
    created_products: set[tuple[str, str]] = set()
    touched_products: set[tuple[str, str]] = set()
    barcodes: dict[str, int] = {}
    codes: dict[str, tuple[int, tuple[str, str]]] = {}
    units_seen: dict[tuple[str, str, str], int] = {}
    stock_lines = []
    zero_price_rows = 0
    no_lot_rows = 0

    for row in rows:
        number = row["_row"]
        trade_name = str(row.get("trade_name") or "").strip()
        unit_name = str(row.get("unit_name") or "").strip()
        if not trade_name or not unit_name:
            result.errors.append(Issue(number, "ต้องมีชื่อการค้าและหน่วยขาย"))
            continue

        strength = str(row.get("strength") or "").strip()
        barcode = str(row.get("barcode") or "").strip()
        code = str(row.get("code") or "").strip()
        if barcode and barcode in barcodes:
            result.errors.append(Issue(number, f"บาร์โค้ด {barcode} ซ้ำกับแถวที่ {barcodes[barcode]} ในไฟล์นี้"))
            continue
        # รหัสเดียวกันซ้ำได้ ถ้าเป็นยาตัวเดียวกันคนละหน่วยขาย — แต่ต้องไม่ใช่ยาคนละตัว
        if code and (seen_before := codes.get(code)) and seen_before[1] != _key(trade_name, strength):
            result.errors.append(
                Issue(number, f"รหัสสินค้า {code} ใช้กับยาคนละตัวในแถวที่ {seen_before[0]} — แก้ไฟล์ให้ตรงกันก่อน")
            )
            continue

        factor = as_int(row.get("factor")) if row.get("factor") not in (None, "") else 1
        if factor == "invalid" or (isinstance(factor, int) and factor < 1):
            result.errors.append(Issue(number, "จำนวนหน่วยเล็กสุดต่อหน่วยขายต้องเป็นจำนวนเต็มตั้งแต่ 1"))
            continue

        prices, price_error, zeroed = _prices(row)
        if price_error:
            result.errors.append(Issue(number, price_error))
            continue
        zero_price_rows += zeroed
        if prices["price1"] == 0:
            result.warnings.append(Issue(number, f"{trade_name}: ราคาขาย 0 บาท — ตรวจอีกครั้งว่าใช่ของแถมจริง"))

        category = category_of(row.get("category"))
        if category == "unknown":
            result.errors.append(
                Issue(number, f"ไม่รู้จักประเภท '{str(row.get('category')).strip()}' — ดูค่าที่ใช้ได้ในไฟล์ตัวอย่าง")
            )
            continue

        unit = _existing_unit_by_barcode(barcode)
        if unit is not None and not _same_product(unit.product, trade_name, strength):
            result.errors.append(
                Issue(number, f"บาร์โค้ด {barcode} ใช้อยู่กับ {unit.product.display_name} — แก้บาร์โค้ดหรือชื่อยาให้ตรงกัน")
            )
            continue

        unit_key = (*_key(trade_name, strength), unit_name.lower())
        if unit_key in units_seen:
            result.errors.append(Issue(number, f"หน่วย '{unit_name}' ของ {trade_name} ซ้ำกับแถวที่ {units_seen[unit_key]}"))
            continue
        units_seen[unit_key] = number

        # รหัสสินค้าคือตัวจับคู่ที่แน่นอนที่สุด (ชื่อยาเปลี่ยนได้ รหัสไม่เปลี่ยน) แล้วค่อยบาร์โค้ด แล้วค่อยชื่อ+ความแรง
        by_code = _find_by_code(products, code)
        if by_code is not None and unit is not None and by_code.pk != unit.product_id:
            result.errors.append(
                Issue(number, f"รหัสสินค้า {code} กับบาร์โค้ด {barcode} ชี้คนละตัวยา — แก้ไฟล์ให้ตรงกันก่อน")
            )
            continue
        product = by_code or (unit.product if unit else _find_product(products, trade_name, strength))
        if by_code is not None and not _same_product(product, trade_name, strength):
            result.warnings.append(
                Issue(number, f"รหัส {code}: เปลี่ยนชื่อจาก {product.display_name} เป็น {trade_name} {strength}".strip())
            )
            product.trade_name = trade_name
            product.strength = strength

        base_unit = str(row.get("base_unit") or "").strip() or (product.base_unit if product else unit_name)
        if product is None:
            new_category = category or default_category
            if new_category is None:
                result.errors.append(
                    Issue(number, f"{trade_name}: ยาตัวใหม่ต้องระบุประเภท — เพิ่มคอลัมน์ 'ประเภท' หรือเลือกประเภทเริ่มต้นในหน้านำเข้า")
                )
                continue
            assumed = category is None
            if assumed:
                result.default_category_rows += 1
            product = Product(
                code=code, trade_name=trade_name, strength=strength, base_unit=base_unit, category=new_category,
                # ประเภทยาเป็นตัวตัดสินว่าต้องให้เภสัชยืนยันไหม ถ้าระบบเดาแทนต้องมีคนมาตรวจ
                needs_review=assumed,
            )
            created_products.add(_key(trade_name, strength))
        elif code and not product.code:
            product.code = code  # เก็บรหัสจากโปรแกรมเดิมไว้ให้การนำเข้าครั้งหน้าจับคู่ได้
        _update_product(product, row, category=category, base_unit=base_unit)
        product.save()
        # Counted per drug, not per row: two units of one drug is one new drug.
        touched_products.add(_key(product.trade_name, product.strength))
        products[_key(product.trade_name, product.strength)] = product

        if unit is None:
            unit = product.units.filter(name__iexact=unit_name).first()
        if unit is None:
            unit = ProductUnit(product=product, name=unit_name)
            result.units_created += 1
        else:
            if unit.factor != factor:
                result.warnings.append(
                    Issue(number, f"{product.display_name}: เปลี่ยนตัวคูณของหน่วย {unit_name} จาก {unit.factor} เป็น {factor}")
                )
            result.units_updated += 1
        unit.name = unit_name
        unit.factor = factor
        unit.barcode = barcode
        for field_name, value in prices.items():
            setattr(unit, field_name, value)
        if yes_no(row.get("is_default")):
            others = product.units.exclude(pk=unit.pk) if unit.pk else product.units.all()
            others.update(is_default=False)
            unit.is_default = True
        unit.save()
        if barcode:
            barcodes[barcode] = number
        if code:
            codes[code] = (number, _key(product.trade_name, product.strength))

        if with_stock:
            line = _stock_line(row, unit, result)
            if line:
                no_lot_rows += line.lot_no == OPENING_LOT and not str(row.get("lot_no") or "").strip()
                stock_lines.append(line)

    if zero_price_rows:
        result.warnings.append(
            Issue(0, f"ราคาระดับ 2–5 เป็น 0 อยู่ {zero_price_rows} แถว — ถือว่ายังไม่ได้ตั้งราคา (ใช้ราคาระดับ 1 แทน) ไม่ใช่ขายฟรี")
        )
    if no_lot_rows:
        result.warnings.append(
            Issue(0, f"ยอดยกมา {no_lot_rows} แถวไม่มีเลขที่ lot — บันทึกเป็น lot \"{OPENING_LOT}\" แยกตามวันหมดอายุ")
        )
    if result.default_category_rows:
        result.warnings.append(
            Issue(0, f"ยาใหม่ {result.default_category_rows} ตัวในไฟล์ไม่ได้บอกประเภท — ใช้ประเภทเริ่มต้นที่เลือกไว้ ตรวจทานอีกครั้งหลังนำเข้า")
        )
    result.products_created = len(created_products)
    result.products_updated = len(touched_products - created_products)
    if result.ok and stock_lines:
        try:
            _post_opening_stock(stock_lines, user=user, source=source)
        except StockError as exc:
            result.errors.append(Issue(0, f"ยอดยกมา: {exc.message}"))


def _prices(row) -> tuple[dict, str | None, bool]:
    """
    Returns (prices, error, had_zero_level). Other shop programs write 0 in the
    price levels the shop never set up; storing that would sell the drug for
    nothing, so a 0 above level 1 means "not set" and falls back to level 1.
    """
    prices = {}
    zeroed = False
    for level, field_name in enumerate(PRICE_FIELDS, start=1):
        value = as_decimal(row.get(field_name))
        if value == "invalid":
            return {}, f"ราคาไม่ถูกต้องในช่อง {field_name.replace('price', 'ราคา ')}", False
        if value is not None and value < 0:
            return {}, "ราคาติดลบไม่ได้", False
        if level > 1 and value == 0:
            value = None
            zeroed = True
        prices[field_name] = value
    if prices["price1"] is None:
        return {}, "ต้องมีราคา 1 (ราคาปลีก)", False
    return prices, None, zeroed


def _key(trade_name: str, strength: str) -> tuple[str, str]:
    return (trade_name.strip().lower(), strength.strip().lower())


def _same_product(product: Product, trade_name: str, strength: str) -> bool:
    return _key(product.trade_name, product.strength) == _key(trade_name, strength)


def _existing_unit_by_barcode(barcode: str):
    return ProductUnit.objects.select_related("product").filter(barcode=barcode).first() if barcode else None


def _find_by_code(seen: dict, code: str):
    if not code:
        return None
    for product in seen.values():
        if product.code == code:
            return product
    return Product.objects.filter(code=code).first()


def _find_product(seen: dict, trade_name: str, strength: str):
    key = _key(trade_name, strength)
    if key in seen:
        return seen[key]
    return Product.objects.filter(trade_name__iexact=trade_name.strip(), strength__iexact=strength.strip()).first()


TEXT_FIELDS = ["generic_name", "dosage_form", "registration_no", "default_dosage", "label_warning", "storage_location"]


def _update_product(product: Product, row, *, category, base_unit: str):
    """Only fills in cells that were actually filled in, so a short file doesn't wipe data."""
    for field_name in TEXT_FIELDS:
        value = str(row.get(field_name) or "").strip()
        if value:
            setattr(product, field_name, value)
    if category:
        product.category = category
    if base_unit:
        product.base_unit = base_unit
    for field_name in ("in_ky11_list", "in_ky13_list"):
        if normalize(row.get(field_name)) not in ("", "-"):
            setattr(product, field_name, yes_no(row.get(field_name)))


def _stock_line(row, unit: ProductUnit, result: ImportResult):
    number = row["_row"]
    qty = as_int(row.get("stock_qty"))
    if qty in (None, 0):
        return None
    if qty == "invalid" or qty < 0:
        result.errors.append(Issue(number, "ยอดยกมาต้องเป็นจำนวนเต็มตั้งแต่ 0"))
        return None
    expiry = parse_expiry(row.get("expiry"))
    if expiry is None:
        result.errors.append(Issue(number, "ยอดยกมาต้องมีวันหมดอายุที่อ่านได้ (เช่น 03/2571 หรือ 14/6/2027)"))
        return None
    # Old systems often track stock by expiry only. A named stand-in keeps the
    # ledger honest about what's known, and each expiry still gets its own lot.
    lot_no = str(row.get("lot_no") or "").strip() or OPENING_LOT
    cost = as_decimal(row.get("unit_cost"))
    if cost == "invalid" or (cost is not None and cost < 0):
        result.errors.append(Issue(number, "ราคาทุนไม่ถูกต้อง"))
        return None
    if expiry < timezone.localdate():
        result.warnings.append(
            Issue(number, f"{unit.product.display_name} lot {lot_no} หมดอายุแล้ว ({thai_date(expiry)}) — รับเข้าได้แต่ขายไม่ได้")
        )
    result.stock_lines += 1
    result.stock_base_qty += qty * unit.factor
    return PurchaseItem(unit=unit, qty=qty, lot_no=lot_no, expiry_date=expiry, unit_cost=cost)


def _post_opening_stock(lines: list[PurchaseItem], *, user, source: str):
    purchase = Purchase.objects.create(
        is_opening_balance=True,
        received_date=timezone.localdate(),
        note=f"นำเข้าจากไฟล์ {source}"[:200],
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    for line in lines:
        line.purchase = purchase
    PurchaseItem.objects.bulk_create(lines)
    post_purchase(purchase, user)


# --- Template ---------------------------------------------------------------

TEMPLATE_HELP = [
    ("รหัสสินค้า", "", "รหัสของร้านหรือรหัสจากโปรแกรมเดิม เช่น #AA-00004 — ใส่ไว้แล้วนำเข้าซ้ำจะจับคู่ได้แม้เปลี่ยนชื่อยา"),
    ("ชื่อการค้า", "ต้องมี", "ชื่อที่พิมพ์บนกล่อง เช่น Amoxicillin"),
    ("ชื่อสามัญ", "", "ชื่อตัวยาสำคัญ ใช้ค้นหาและจับคู่กลุ่มยาสำหรับแจ้งเตือนแพ้ยา"),
    ("ความแรง", "", "เช่น 500 mg — ชื่อการค้า + ความแรง คือตัวระบุว่าเป็นยาตัวเดียวกัน"),
    ("รูปแบบยา", "", "เช่น เม็ด แคปซูล น้ำเชื่อม"),
    ("ประเภท", "ต้องมี", "สินค้าทั่วไป / ยาสามัญประจำบ้าน / ยาบรรจุเสร็จ (ไม่ใช่ยาอันตราย) / ยาอันตราย / ยาควบคุมพิเศษ"),
    ("หน่วยเล็กสุด", "ต้องมี", "หน่วยที่ใช้นับสต็อก เช่น เม็ด แคปซูล ขวด"),
    ("หน่วยขาย", "ต้องมี", "หน่วยของแถวนี้ เช่น แผง — ยาตัวเดียวกันขายหลายหน่วย ให้ใส่หลายแถว"),
    ("จำนวนหน่วยเล็กสุดต่อหน่วยขาย", "ต้องมี", "เช่น แผงละ 10 เม็ด ใส่ 10 · ถ้าเป็นหน่วยเล็กสุดเองใส่ 1"),
    ("บาร์โค้ด", "", "ของหน่วยขายนี้ ใช้จับคู่ตอนนำเข้าซ้ำด้วย"),
    ("หน่วยขายหลัก", "", "ใส่ ใช่ ในหน่วยที่ขายบ่อยที่สุดของยาตัวนั้น"),
    ("ราคา1", "ต้องมี", "ราคาปลีก"),
    ("ราคา2–ราคา5", "", "ราคาตามระดับลูกค้า เว้นว่างได้ = ใช้ราคา 1"),
    ("เลขทะเบียนตำรับ", "", "ใช้ในรายงาน ขย.9"),
    ("ขย.11 / ขย.13", "", "ใส่ ใช่ ถ้ายาตัวนั้นต้องลงบัญชี/รายงานตามประกาศ"),
    ("วิธีใช้ / คำเตือน / ที่เก็บ", "", "วิธีใช้และคำเตือนจะขึ้นบนฉลากยา ที่เก็บช่วยให้หยิบยาเร็วขึ้น"),
    ("ยอดยกมา", "", "จำนวนที่มีอยู่จริง นับเป็นหน่วยขายของแถวนี้ — เว้นว่างถ้ายังไม่นับสต็อก"),
    ("วันหมดอายุ", "ถ้ามียอดยกมา", "พิมพ์ตามกล่องได้ เช่น 03/2028, 03/71, 31/03/2571, 14/6/2027"),
    ("lot", "", f"ถ้าไม่มีเลข lot เว้นว่างได้ ระบบจะบันทึกเป็น lot \"{OPENING_LOT}\" แยกตามวันหมดอายุ"),
    ("ราคาทุน", "", "ทุนต่อหน่วยขายของแถวนี้ ใช้ดูกำไรภายหลัง"),
]

TEMPLATE_ROWS = [
    ["AMOX-500", "Amoxicillin", "Amoxicillin trihydrate", "500 mg", "แคปซูล", "ยาอันตราย", "แคปซูล", "แผง", 10,
     "2000000000042", "ใช่", 40, 38, 36, 34, 30, "", "", "", "รับประทานครั้งละ 1 แคปซูล วันละ 3 ครั้ง หลังอาหาร",
     "รับประทานติดต่อกันจนหมด", "ชั้น B2", 5, "AX118", "03/2571", 230],
    ["AMOX-500", "Amoxicillin", "Amoxicillin trihydrate", "500 mg", "แคปซูล", "ยาอันตราย", "แคปซูล", "กล่อง", 100,
     "2000000000059", "", 380, 360, 340, 320, 290, "", "", "", "", "", "", "", "", "", ""],
    ["PARA-500", "Paracetamol", "Paracetamol", "500 mg", "เม็ด", "ยาสามัญประจำบ้าน", "เม็ด", "แผง", 10,
     "2000000000028", "ใช่", 15, 14, 13, 12, 10, "", "", "", "รับประทานครั้งละ 1–2 เม็ด ทุก 4–6 ชั่วโมง เวลาปวดหรือมีไข้",
     "ไม่ควรรับประทานเกินวันละ 8 เม็ด", "ชั้น A1", 60, "P2405", "12/2570", 9],
]


def template_workbook() -> bytes:
    """The blank form the shop fills in, with examples and an explanation sheet."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "ยา"
    headers = [names[0] for names in COLUMNS.values()]
    sheet.append(headers)
    for row in TEMPLATE_ROWS:
        sheet.append(row)
    for index, header in enumerate(headers, start=1):
        cell = sheet.cell(row=1, column=index)
        cell.font = Font(bold=True)
        sheet.column_dimensions[cell.column_letter].width = max(12, len(header) + 4)
    sheet.freeze_panes = "A2"

    help_sheet = workbook.create_sheet("คำอธิบาย")
    help_sheet.append(["คอลัมน์", "บังคับ", "คำอธิบาย"])
    for line in TEMPLATE_HELP:
        help_sheet.append(list(line))
    for column, width in zip("ABC", (32, 14, 90)):
        help_sheet.column_dimensions[column].width = width
    for column in range(1, 4):
        help_sheet.cell(row=1, column=column).font = Font(bold=True)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
