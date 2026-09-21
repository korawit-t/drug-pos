from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class PriceLevel(models.Model):
    """ระดับราคา 1–5 มีครบ 5 แถวเสมอ (สร้างใน migration) เปลี่ยนได้แค่ชื่อ"""

    level = models.PositiveSmallIntegerField("ระดับ", primary_key=True)
    name = models.CharField("ชื่อระดับราคา", max_length=50)

    class Meta:
        verbose_name = "ระดับราคา"
        verbose_name_plural = "ระดับราคา"
        ordering = ["level"]

    def __str__(self):
        return f"{self.level} · {self.name}"


class Supplier(models.Model):
    name = models.CharField("ชื่อผู้ขาย", max_length=200)
    address = models.TextField("ที่อยู่", blank=True)
    phone = models.CharField("เบอร์โทร", max_length=50, blank=True)
    license_no = models.CharField("เลขที่ใบอนุญาต", max_length=100, blank=True)

    class Meta:
        verbose_name = "ผู้ขาย (Supplier)"
        verbose_name_plural = "ผู้ขาย (Supplier)"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    class Category(models.TextChoices):
        GENERAL = "general", "สินค้าทั่วไป"
        HOUSEHOLD = "household", "ยาสามัญประจำบ้าน"
        READY_PACKED = "ready_packed", "ยาบรรจุเสร็จ (ไม่ใช่ยาอันตราย)"
        DANGEROUS = "dangerous", "ยาอันตราย"
        SPECIAL_CONTROLLED = "special_controlled", "ยาควบคุมพิเศษ"

    trade_name = models.CharField("ชื่อการค้า", max_length=200)
    generic_name = models.CharField("ชื่อสามัญ", max_length=200, blank=True)
    strength = models.CharField("ความแรง", max_length=100, blank=True, help_text="เช่น 500 mg")
    dosage_form = models.CharField("รูปแบบยา", max_length=100, blank=True, help_text="เช่น เม็ด แคปซูล น้ำเชื่อม")
    registration_no = models.CharField("เลขทะเบียนตำรับยา", max_length=50, blank=True)
    tmt_code = models.CharField("รหัส TMT", max_length=20, blank=True)
    category = models.CharField("ประเภท", max_length=30, choices=Category.choices, default=Category.GENERAL)
    in_ky11_list = models.BooleanField(
        "ต้องลงบัญชี ขย.11", default=False, help_text="ยาอันตรายที่ อย. ประกาศให้ทำบัญชีการขาย — ต้องกรอกชื่อผู้ซื้อ"
    )
    in_ky13_list = models.BooleanField("ต้องรายงาน ขย.13", default=False)
    base_unit = models.CharField("หน่วยเล็กสุด", max_length=30, help_text="หน่วยที่ใช้นับสต็อก เช่น เม็ด แคปซูล ขวด")
    default_dosage = models.CharField("วิธีใช้ (ค่าเริ่มต้นบนฉลาก)", max_length=300, blank=True)
    label_warning = models.CharField("คำเตือนบนฉลาก", max_length=300, blank=True)
    storage_location = models.CharField("ที่เก็บ", max_length=100, blank=True)
    is_active = models.BooleanField("ใช้งาน", default=True)

    class Meta:
        verbose_name = "สินค้า / ยา"
        verbose_name_plural = "สินค้า / ยา"
        ordering = ["trade_name"]

    def __str__(self):
        return self.display_name

    @property
    def display_name(self) -> str:
        return f"{self.trade_name} {self.strength}".strip()

    @property
    def needs_pharmacist(self) -> bool:
        return self.category in (self.Category.DANGEROUS, self.Category.SPECIAL_CONTROLLED)

    @property
    def needs_prescription(self) -> bool:
        return self.category == self.Category.SPECIAL_CONTROLLED

    @property
    def needs_buyer_name(self) -> bool:
        return self.in_ky11_list

    @property
    def is_drug(self) -> bool:
        return self.category != self.Category.GENERAL


class ProductUnit(models.Model):
    """
    หน่วยขาย เช่น เม็ด (x1) แผง (x10) กล่อง (x100)
    ราคาระดับ 2–5 เว้นว่างได้ — ถ้าว่างจะใช้ราคาระดับ 1
    """

    product = models.ForeignKey(Product, verbose_name="สินค้า", on_delete=models.CASCADE, related_name="units")
    name = models.CharField("หน่วย", max_length=30)
    factor = models.PositiveIntegerField("จำนวนหน่วยเล็กสุด", default=1, help_text="1 หน่วยนี้ = กี่หน่วยเล็กสุด")
    barcode = models.CharField("บาร์โค้ด", max_length=50, blank=True, db_index=True)
    is_default = models.BooleanField("หน่วยขายหลัก", default=False)
    price1 = models.DecimalField("ราคา 1", max_digits=10, decimal_places=2)
    price2 = models.DecimalField("ราคา 2", max_digits=10, decimal_places=2, null=True, blank=True)
    price3 = models.DecimalField("ราคา 3", max_digits=10, decimal_places=2, null=True, blank=True)
    price4 = models.DecimalField("ราคา 4", max_digits=10, decimal_places=2, null=True, blank=True)
    price5 = models.DecimalField("ราคา 5", max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = "หน่วยขาย"
        verbose_name_plural = "หน่วยขาย"
        ordering = ["product", "factor"]
        constraints = [
            models.UniqueConstraint(fields=["product", "name"], name="unique_unit_name_per_product"),
            models.UniqueConstraint(fields=["barcode"], condition=~Q(barcode=""), name="unique_barcode"),
            models.CheckConstraint(condition=Q(factor__gte=1), name="unit_factor_positive"),
        ]

    def __str__(self):
        return f"{self.product.display_name} — {self.name} (x{self.factor})"

    def price_for(self, level: int) -> Decimal:
        price = getattr(self, f"price{level}", None) if 1 <= level <= 5 else None
        return self.price1 if price is None else price


class Lot(models.Model):
    """ยาหนึ่ง lot — สต็อกคงเหลือ (qty_on_hand) เป็นยอดสะสมจาก StockMovement เสมอ"""

    product = models.ForeignKey(Product, verbose_name="สินค้า", on_delete=models.PROTECT, related_name="lots")
    lot_no = models.CharField("เลขที่ lot", max_length=50)
    expiry_date = models.DateField("วันหมดอายุ")
    cost_per_base = models.DecimalField("ต้นทุนต่อหน่วยเล็กสุด", max_digits=12, decimal_places=4, default=0)
    qty_on_hand = models.IntegerField("คงเหลือ (หน่วยเล็กสุด)", default=0)
    created_at = models.DateTimeField("รับเข้าครั้งแรก", auto_now_add=True)

    class Meta:
        verbose_name = "Lot"
        verbose_name_plural = "Lot / วันหมดอายุ"
        ordering = ["product", "expiry_date"]
        constraints = [
            models.UniqueConstraint(fields=["product", "lot_no", "expiry_date"], name="unique_lot"),
        ]

    def __str__(self):
        return f"{self.product.display_name} · lot {self.lot_no}"


class StockMovement(models.Model):
    """
    สมุดบัญชีสต็อก: ทุกการเปลี่ยนแปลงเป็นหนึ่งแถว ไม่มีการแก้หรือลบ
    qty เป็นหน่วยเล็กสุด บวก = เข้า ลบ = ออก
    """

    class Kind(models.TextChoices):
        RECEIVE = "receive", "รับเข้า"
        OPENING = "opening", "ยอดยกมา"
        SALE = "sale", "ขาย"
        VOID = "void", "ยกเลิกบิล"
        ADJUST = "adjust", "ปรับยอด"

    lot = models.ForeignKey(Lot, verbose_name="Lot", on_delete=models.PROTECT, related_name="movements")
    kind = models.CharField("ประเภท", max_length=20, choices=Kind.choices)
    qty = models.IntegerField("จำนวน (หน่วยเล็กสุด)")
    created_at = models.DateTimeField("เวลา", auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="ผู้ทำรายการ", null=True, on_delete=models.PROTECT, related_name="+"
    )
    purchase_item = models.ForeignKey(
        "PurchaseItem", null=True, blank=True, on_delete=models.PROTECT, related_name="movements"
    )
    note = models.CharField("หมายเหตุ", max_length=200, blank=True)

    class Meta:
        verbose_name = "ความเคลื่อนไหวสต็อก"
        verbose_name_plural = "ความเคลื่อนไหวสต็อก"
        ordering = ["-created_at", "-id"]


class Purchase(models.Model):
    """ใบรับยา — บันทึกเข้าสต็อกแล้วแก้ไม่ได้ (ข้อมูลไปลง ขย.9)"""

    class Status(models.TextChoices):
        DRAFT = "draft", "ร่าง"
        POSTED = "posted", "บันทึกเข้าสต็อกแล้ว"

    is_opening_balance = models.BooleanField(
        "ยอดยกมา", default=False, help_text="ใช้ตอนเริ่มใช้ระบบ นับสต็อกที่มีอยู่แล้ว — ไม่ไปลง ขย.9"
    )
    supplier = models.ForeignKey(
        Supplier, verbose_name="ผู้ขาย", null=True, blank=True, on_delete=models.PROTECT, related_name="purchases"
    )
    invoice_no = models.CharField("เลขที่ใบกำกับ/ใบส่งของ", max_length=50, blank=True)
    invoice_date = models.DateField("วันที่ในใบกำกับ", null=True, blank=True)
    received_date = models.DateField("วันที่รับยา")
    note = models.CharField("หมายเหตุ", max_length=200, blank=True)
    status = models.CharField("สถานะ", max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField("สร้างเมื่อ", default=timezone.now, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="ผู้สร้าง", null=True, blank=True, editable=False,
        on_delete=models.PROTECT, related_name="+",
    )
    posted_at = models.DateTimeField("บันทึกเข้าสต็อกเมื่อ", null=True, blank=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="ผู้บันทึก", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )

    class Meta:
        verbose_name = "ใบรับยา"
        verbose_name_plural = "ใบรับยา"
        ordering = ["-received_date", "-id"]

    def __str__(self):
        if self.is_opening_balance:
            return f"ยอดยกมา {self.received_date}"
        return f"{self.supplier or '-'} · {self.invoice_no or 'ไม่มีเลขที่'} · {self.received_date}"

    def clean(self):
        if not self.is_opening_balance and not self.supplier_id:
            raise ValidationError({"supplier": "ใบรับยาต้องระบุผู้ขาย (ยกเว้นยอดยกมา)"})


class PurchaseItem(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="items")
    unit = models.ForeignKey(ProductUnit, verbose_name="สินค้า / หน่วย", on_delete=models.PROTECT, related_name="+")
    qty = models.PositiveIntegerField("จำนวน")
    # A draft may be saved half-filled; lot, expiry and cost are required when it's
    # posted to stock. An empty cost ("not entered yet") is different from 0 (free goods).
    lot_no = models.CharField("เลขที่ lot", max_length=50, blank=True)
    expiry_date = models.DateField("วันหมดอายุ", null=True, blank=True)
    unit_cost = models.DecimalField(
        "ราคาทุนต่อหน่วย", max_digits=10, decimal_places=2, null=True, blank=True, help_text="ของแถมใส่ 0"
    )
    lot = models.ForeignKey(Lot, null=True, blank=True, editable=False, on_delete=models.PROTECT, related_name="+")

    class Meta:
        verbose_name = "รายการรับยา"
        verbose_name_plural = "รายการรับยา"

    @property
    def base_qty(self) -> int:
        return self.qty * self.unit.factor
