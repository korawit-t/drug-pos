import sqlite3
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = (
        "สำรองฐานข้อมูลขณะระบบเปิดใช้งานอยู่ได้อย่างปลอดภัย (ใช้ SQLite backup API ไม่ใช่การ copy ไฟล์) "
        "เช่น python manage.py backup_db --dest D:\\backup"
    )

    def add_arguments(self, parser):
        parser.add_argument("--dest", required=True, help="โฟลเดอร์ปลายทาง เช่น USB หรือโฟลเดอร์ Google Drive")
        parser.add_argument("--keep", type=int, default=30, help="เก็บไฟล์สำรองล่าสุดไว้กี่ไฟล์ (ค่าเริ่มต้น 30)")

    def handle(self, *args, dest, keep, **options):
        dest_dir = Path(dest)
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / f"drugpos-{timezone.localtime():%Y%m%d-%H%M%S}.sqlite3"

        source = sqlite3.connect(settings.DATABASES["default"]["NAME"])
        copy = sqlite3.connect(target)
        try:
            source.backup(copy)
            result = copy.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            copy.close()
            source.close()
        if result != "ok":
            raise CommandError(f"ไฟล์สำรองไม่สมบูรณ์: {result}")

        backups = sorted(dest_dir.glob("drugpos-*.sqlite3"))
        for old in backups[: max(len(backups) - keep, 0)]:
            old.unlink()
        self.stdout.write(self.style.SUCCESS(f"สำรองแล้ว: {target}"))
