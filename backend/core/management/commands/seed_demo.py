from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from core.models import ShopSettings
from inventory.models import PriceLevel, Product, ProductUnit, Purchase, PurchaseItem, Supplier
from inventory.services import post_purchase
from sales.models import Customer

C = Product.Category

# Demo data only. Categories follow common Thai classification but are not
# checked against registrations; the ขย.11 item is fictional on purpose.
# Barcodes use the 200-prefix (in-store range) so they can't clash with real products.
# units: (name, factor, barcode, [price1..price5], is_default)   lots: (lot_no, days_to_expiry, base_qty)
PRODUCTS = [
    dict(
        trade_name="Paracetamol", generic_name="Paracetamol", strength="500 mg", dosage_form="เม็ด",
        category=C.HOUSEHOLD, base_unit="เม็ด", storage_location="ชั้น A1",
        default_dosage="รับประทานครั้งละ 1–2 เม็ด ทุก 4–6 ชั่วโมง เวลาปวดหรือมีไข้",
        label_warning="ไม่ควรรับประทานเกินวันละ 8 เม็ด",
        units=[("เม็ด", 1, "2000000000011", [1.5], False),
               ("แผง", 10, "2000000000028", [15, 14, 13, 12, 10], True),
               ("กล่อง", 100, "2000000000035", [140, 130, 125, 115, 100], False)],
        lots=[("P2405", 500, 600)],
    ),
    dict(
        trade_name="Amoxicillin", generic_name="Amoxicillin trihydrate", strength="500 mg", dosage_form="แคปซูล",
        category=C.DANGEROUS, base_unit="แคปซูล", storage_location="ชั้น B2",
        default_dosage="รับประทานครั้งละ 1 แคปซูล วันละ 3 ครั้ง หลังอาหาร",
        label_warning="รับประทานติดต่อกันจนหมด",
        units=[("แผง", 10, "2000000000042", [40, 38, 36, 34, 30], True),
               ("กล่อง", 100, "2000000000059", [380, 360, 340, 320, 290], False)],
        lots=[("AX118", 150, 50)],  # near expiry: FEFO takes this one first
    ),
    dict(
        trade_name="Cetirizine", generic_name="Cetirizine dihydrochloride", strength="10 mg", dosage_form="เม็ด",
        category=C.DANGEROUS, base_unit="เม็ด", storage_location="ชั้น B1",
        default_dosage="รับประทานครั้งละ 1 เม็ด วันละ 1 ครั้ง ก่อนนอน",
        label_warning="อาจทำให้ง่วงซึม",
        units=[("แผง", 10, "2000000000066", [35, 33, 31, 29, 25], True)],
        lots=[("CZ09", -10, 10), ("CZ31", 400, 100)],  # CZ09 already expired — must never be sold
    ),
    dict(
        trade_name="Chlorpheniramine", generic_name="Chlorpheniramine maleate", strength="4 mg", dosage_form="เม็ด",
        category=C.HOUSEHOLD, base_unit="เม็ด", storage_location="ชั้น A2",
        default_dosage="รับประทานครั้งละ 1 เม็ด วันละ 3 ครั้ง หลังอาหาร",
        label_warning="ทำให้ง่วงซึม ห้ามขับขี่ยานพาหนะ",
        units=[("แผง", 10, "2000000000073", [10, 9, 9, 8, 7], True)],
        lots=[("CP77", 600, 200)],
    ),
    dict(
        trade_name="Omeprazole", generic_name="Omeprazole", strength="20 mg", dosage_form="แคปซูล",
        category=C.DANGEROUS, base_unit="แคปซูล", storage_location="ชั้น B3",
        default_dosage="รับประทานครั้งละ 1 แคปซูล วันละ 1 ครั้ง ก่อนอาหารเช้า 30 นาที",
        units=[("แผง", 10, "2000000000080", [45, 42, 40, 38, 35], True)],
        lots=[("OM55", 450, 100)],
    ),
    dict(
        trade_name="Ibuprofen", generic_name="Ibuprofen", strength="400 mg", dosage_form="เม็ด",
        category=C.DANGEROUS, base_unit="เม็ด", storage_location="ชั้น B1",
        default_dosage="รับประทานครั้งละ 1 เม็ด วันละ 3 ครั้ง หลังอาหารทันที",
        label_warning="ห้ามใช้ในผู้ที่เป็นโรคกระเพาะอาหาร",
        units=[("แผง", 10, "2000000000097", [25, 24, 22, 21, 18], True)],
        lots=[("IB12", 380, 100)],
    ),
    dict(
        trade_name="Prednisolone", generic_name="Prednisolone", strength="5 mg", dosage_form="เม็ด",
        category=C.SPECIAL_CONTROLLED, base_unit="เม็ด", storage_location="ตู้ยาควบคุม",
        default_dosage="รับประทานตามแพทย์สั่ง",
        label_warning="ห้ามหยุดยาเอง",
        units=[("แผง", 10, "2000000000103", [20, 19, 18, 17, 15], True)],
        lots=[("PD77", 400, 100)],
    ),
    dict(
        trade_name="ยาแก้ไอน้ำเชื่อม (ตัวอย่าง ขย.11)", generic_name="ข้อมูลสมมติสำหรับทดลองระบบ", strength="60 ml",
        dosage_form="น้ำเชื่อม", category=C.DANGEROUS, in_ky11_list=True, base_unit="ขวด",
        storage_location="ชั้น C1",
        default_dosage="รับประทานครั้งละ 1 ช้อนชา วันละ 3 ครั้ง",
        units=[("ขวด", 1, "2000000000110", [60, 58, 55, 52, 50], True)],
        lots=[("DX01", 300, 12)],
    ),
    dict(
        trade_name="ผงเกลือแร่ ORS", generic_name="Oral rehydration salts", strength="", dosage_form="ผง",
        category=C.HOUSEHOLD, base_unit="ซอง", storage_location="ชั้น A3",
        default_dosage="ละลายน้ำสุก 1 แก้ว (250 มล.) ดื่มจิบบ่อย ๆ",
        units=[("ซอง", 1, "2000000000127", [6], True),
               ("กล่อง", 50, "2000000000134", [270, 260], False)],
        lots=[("OR88", 700, 200)],
    ),
    dict(
        trade_name="Antacid", generic_name="Aluminium hydroxide + Magnesium hydroxide", strength="240 ml",
        dosage_form="ยาน้ำแขวนตะกอน", category=C.HOUSEHOLD, base_unit="ขวด", storage_location="ชั้น A3",
        default_dosage="รับประทานครั้งละ 1–2 ช้อนโต๊ะ หลังอาหารและก่อนนอน",
        label_warning="เขย่าขวดก่อนใช้",
        units=[("ขวด", 1, "2000000000141", [45, 43, 41, 39, 35], True)],
        lots=[("AL20", 520, 24)],
    ),
    dict(
        trade_name="Povidone-iodine", generic_name="Povidone-iodine 10%", strength="30 ml", dosage_form="ยาใช้ภายนอก",
        category=C.HOUSEHOLD, base_unit="ขวด", storage_location="ชั้น A4",
        default_dosage="ใช้ทาภายนอก ทาแผลวันละ 1–2 ครั้ง",
        label_warning="ห้ามรับประทาน",
        units=[("ขวด", 1, "2000000000158", [35, 33, 32, 30, 28], True)],
        lots=[("PV03", 640, 30)],
    ),
    dict(
        trade_name="หน้ากากอนามัย", generic_name="", strength="", dosage_form="",
        category=C.GENERAL, base_unit="ชิ้น", storage_location="หน้าร้าน",
        units=[("ชิ้น", 1, "2000000000165", [3], False),
               ("กล่อง", 50, "2000000000172", [60, 55, 50, 45, 40], True)],
        lots=[("MK01", 900, 500)],
    ),
    dict(
        trade_name="วิตามินซี 1000 mg", generic_name="", strength="30 เม็ด", dosage_form="",
        category=C.GENERAL, base_unit="กระปุก", storage_location="หน้าร้าน",
        units=[("กระปุก", 1, "2000000000189", [250, 240, 230, 220, 200], True)],
        lots=[("VC11", 480, 20)],
    ),
]


class Command(BaseCommand):
    help = "สร้างข้อมูลตัวอย่างสำหรับทดลองระบบ (ใช้กับฐานข้อมูลใหม่เท่านั้น)"

    def handle(self, *args, **options):
        if Product.objects.exists() or User.objects.exists():
            raise CommandError("ฐานข้อมูลนี้มีข้อมูลอยู่แล้ว — seed_demo ใช้กับฐานข้อมูลใหม่เท่านั้น")
        with transaction.atomic():
            self._seed()
        self.stdout.write(self.style.SUCCESS("สร้างข้อมูลตัวอย่างแล้ว"))
        self.stdout.write(
            "ผู้ใช้ตัวอย่าง (รหัสผ่าน / PIN):\n"
            "  admin   admin1234  (เจ้าของร้าน เข้าหลังร้านได้)\n"
            "  staff   staff1234  (พนักงานหน้าร้าน)\n"
            "  pharm1  pharm1234  PIN 1234  ภก.สมศรี ใจดี\n"
            "  pharm2  pharm1234  PIN 5678  ภญ.วิไล รักษ์ยา\n"
            "เปลี่ยนรหัสผ่านทั้งหมดก่อนใช้งานจริง"
        )

    def _seed(self):
        shop = ShopSettings.load()
        shop.name = "ร้านยาตัวอย่าง (ทดลองระบบ)"
        shop.address = "123 ถนนตัวอย่าง อำเภอเมือง จังหวัดขอนแก่น"
        shop.phone = "043-000-000"
        shop.license_no = "ขย.1 เลขที่ ตัวอย่าง"
        shop.receipt_footer = "ขอบคุณที่ใช้บริการ · สอบถามการใช้ยาได้ที่เภสัชกร"
        shop.save()

        names = {1: "ราคาปลีก", 2: "นักศึกษา/บุคลากร", 3: "สมาชิก", 4: "คลินิก/ร้านยา", 5: "ราคาพิเศษ"}
        for level, name in names.items():
            PriceLevel.objects.filter(pk=level).update(name=name)

        admin = User.objects.create_superuser("admin", password="admin1234", display_name="เจ้าของร้าน")
        User.objects.create_user("staff", password="staff1234", display_name="พนักงานหน้าร้าน")
        for username, name, license_no, pin in [
            ("pharm1", "ภก.สมศรี ใจดี", "ภ.10001", "1234"),
            ("pharm2", "ภญ.วิไล รักษ์ยา", "ภ.10002", "5678"),
        ]:
            pharmacist = User(
                username=username, display_name=name, license_no=license_no,
                role=User.Role.PHARMACIST, is_staff=True,
            )
            pharmacist.set_password("pharm1234")
            pharmacist.set_pin(pin)
            pharmacist.save()

        supplier = Supplier.objects.create(
            name="บริษัท ยาดีฟาร์มา จำกัด (ตัวอย่าง)", address="99 ถนนมิตรภาพ ขอนแก่น", license_no="ขย.6 ตัวอย่าง"
        )
        Supplier.objects.create(name="บริษัท เภสัชภัณฑ์สยาม จำกัด (ตัวอย่าง)")

        today = timezone.localdate()
        opening = Purchase.objects.create(is_opening_balance=True, received_date=today - timedelta(days=30))
        units_by_product = {}
        for spec in PRODUCTS:
            spec = dict(spec)
            unit_specs, lot_specs = spec.pop("units"), spec.pop("lots")
            product = Product.objects.create(**spec)
            units = []
            for name, factor, barcode, prices, is_default in unit_specs:
                price_fields = {f"price{i + 1}": Decimal(str(p)) for i, p in enumerate(prices)}
                units.append(
                    ProductUnit.objects.create(
                        product=product, name=name, factor=factor, barcode=barcode, is_default=is_default,
                        **price_fields,
                    )
                )
            units_by_product[product.trade_name] = units
            base_unit = min(units, key=lambda u: u.factor)
            for lot_no, days, base_qty in lot_specs:
                PurchaseItem.objects.create(
                    purchase=opening, unit=base_unit, qty=base_qty // base_unit.factor, lot_no=lot_no,
                    expiry_date=today + timedelta(days=days), unit_cost=base_unit.price1 * Decimal("0.6"),
                )
        post_purchase(opening, admin)

        # A normal delivery from a supplier today, so ขย.9 has something to show.
        delivery = Purchase.objects.create(
            supplier=supplier, invoice_no="IV-0921-001", invoice_date=today, received_date=today
        )
        amox_box = units_by_product["Amoxicillin"][1]
        para_box = units_by_product["Paracetamol"][2]
        PurchaseItem.objects.create(
            purchase=delivery, unit=amox_box, qty=2, lot_no="AX203",
            expiry_date=today + timedelta(days=700), unit_cost=Decimal("230"),
        )
        PurchaseItem.objects.create(
            purchase=delivery, unit=para_box, qty=5, lot_no="P2511",
            expiry_date=today + timedelta(days=800), unit_cost=Decimal("85"),
        )
        post_purchase(delivery, admin)

        Customer.objects.create(
            name="ลูกค้าตัวอย่าง นักศึกษา", phone="080-000-0001", price_level_id=2,
            allergies="Penicillin (ผื่นลมพิษ)",
        )
        Customer.objects.create(
            name="สมชาย ใจดี (ตัวอย่าง)", phone="080-000-0002", price_level_id=3,
            chronic_conditions="ความดันโลหิตสูง",
        )
        Customer.objects.create(name="คลินิกตัวอย่าง", phone="043-000-111", price_level_id=4)
