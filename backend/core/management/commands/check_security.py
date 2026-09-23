from django.core.management.base import BaseCommand

from core.security import security_warnings


class Command(BaseCommand):
    help = "ตรวจสิ่งที่ต้องแก้ก่อนใช้งานจริง เช่น รหัสผ่านตัวอย่างและ PIN ที่เดาง่าย"

    def handle(self, *args, **options):
        warnings = security_warnings()
        if not warnings:
            self.stdout.write(self.style.SUCCESS("ไม่พบปัญหาที่ตรวจอัตโนมัติได้"))
            return
        for warning in warnings:
            self.stdout.write(self.style.WARNING(f"- {warning}"))
        self.stdout.write("")
        self.stdout.write("แก้ตามรายการด้านบนแล้วรันคำสั่งนี้อีกครั้ง")
        raise SystemExit(1)
