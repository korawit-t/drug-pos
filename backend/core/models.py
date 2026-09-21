from django.db import models


class ShopSettings(models.Model):
    """ข้อมูลร้าน ใช้บนใบเสร็จ ฉลากยา และรายงาน มีแถวเดียวเสมอ (pk=1)"""

    name = models.CharField("ชื่อร้าน", max_length=200, default="ร้านยา")
    address = models.TextField("ที่อยู่", blank=True)
    phone = models.CharField("เบอร์โทร", max_length=50, blank=True)
    license_no = models.CharField("เลขที่ใบอนุญาตขายยา", max_length=100, blank=True)
    tax_id = models.CharField("เลขประจำตัวผู้เสียภาษี", max_length=20, blank=True)
    promptpay_id = models.CharField(
        "พร้อมเพย์ (เบอร์มือถือหรือเลขประจำตัวผู้เสียภาษี)",
        max_length=20,
        blank=True,
        help_text="ถ้าว่างไว้ หน้ารับเงินโอนจะไม่แสดง QR",
    )
    receipt_footer = models.CharField("ข้อความท้ายใบเสร็จ", max_length=200, blank=True)
    near_expiry_days = models.PositiveIntegerField(
        "เตือนยาใกล้หมดอายุล่วงหน้า (วัน)", default=180
    )

    class Meta:
        verbose_name = "ข้อมูลร้าน"
        verbose_name_plural = "ข้อมูลร้าน"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "ShopSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
