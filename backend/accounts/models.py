from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        STAFF = "staff", "พนักงาน"
        PHARMACIST = "pharmacist", "เภสัชกร"

    role = models.CharField("บทบาท", max_length=20, choices=Role.choices, default=Role.STAFF)
    display_name = models.CharField(
        "ชื่อที่แสดง", max_length=100, blank=True, help_text="เช่น ภก.สมศรี ใจดี — ใช้บนฉลากและรายงาน"
    )
    license_no = models.CharField("เลขที่ใบอนุญาตประกอบวิชาชีพ", max_length=30, blank=True)
    # PIN is separate from the login password: counters often stay logged in
    # as one shared user, so the PIN is what proves which pharmacist dispensed.
    pin_hash = models.CharField(max_length=128, blank=True, editable=False)
    pin_failed_count = models.PositiveSmallIntegerField(default=0, editable=False)
    pin_locked_until = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "ผู้ใช้"
        verbose_name_plural = "ผู้ใช้"

    @property
    def is_pharmacist(self) -> bool:
        return self.role == self.Role.PHARMACIST

    @property
    def label_name(self) -> str:
        return self.display_name or self.get_full_name() or self.username

    def set_pin(self, raw_pin: str) -> None:
        self.pin_hash = make_password(raw_pin)
        self.pin_failed_count = 0
        self.pin_locked_until = None

    def check_pin(self, raw_pin: str) -> bool:
        return bool(self.pin_hash) and check_password(raw_pin, self.pin_hash)


class PinAttempt(models.Model):
    """Every PIN entry, right or wrong — who, for what, from which counter."""

    class Action(models.TextChoices):
        DISPENSE = "dispense", "ยืนยันจ่ายยา"
        VOID = "void", "ยกเลิกบิล"

    created_at = models.DateTimeField("เวลา", auto_now_add=True)
    pharmacist = models.ForeignKey(
        User, verbose_name="เภสัชกร", on_delete=models.PROTECT, related_name="pin_attempts"
    )
    requested_by = models.ForeignKey(
        User, verbose_name="เครื่องที่ login เป็น", null=True, on_delete=models.SET_NULL, related_name="+"
    )
    action = models.CharField("งาน", max_length=20, choices=Action.choices)
    success = models.BooleanField("ผ่าน")
    detail = models.CharField("รายละเอียด", max_length=200, blank=True)
    terminal = models.CharField("เครื่อง (IP)", max_length=64, blank=True)

    class Meta:
        verbose_name = "ประวัติการใส่ PIN"
        verbose_name_plural = "ประวัติการใส่ PIN"
        ordering = ["-created_at"]
