import json
from decimal import Decimal

from django.test import Client, TestCase

from accounts.models import User

from .models import Allergen, Product, ProductUnit
from .services import ProductData, ProductError, UnitData, save_product
from .tests import make_product, make_unit, receive


def unit_data(name="แผง", factor=10, prices=("40", None, None, None, None), **kwargs):
    return UnitData(
        name=name, factor=factor,
        prices=[Decimal(p) if p is not None else None for p in prices],
        **kwargs,
    )


def product_data(**kwargs):
    defaults = dict(
        trade_name="Ibuprofen", base_unit="เม็ด", category=Product.Category.DANGEROUS,
        units=[unit_data()],
    )
    return ProductData(**{**defaults, **kwargs})


class SaveProductTests(TestCase):
    def test_creates_a_drug_with_its_units_and_default_unit(self):
        product = save_product(product_data(
            code="IBU-400", generic_name="Ibuprofen", strength="400 mg",
            units=[unit_data("เม็ด", 1, ("4", "3.5", None, None, None)), unit_data("แผง", 10)],
        ))
        self.assertEqual(product.display_name, "Ibuprofen 400 mg")
        self.assertEqual(product.units.count(), 2)
        # ไม่ได้เลือกหน่วยหลัก ระบบเลือกหน่วยเล็กสุดให้
        self.assertEqual(product.units.get(is_default=True).name, "เม็ด")
        tablet = product.units.get(name="เม็ด")
        self.assertEqual((tablet.price1, tablet.price2, tablet.price3), (Decimal("4"), Decimal("3.5"), None))
        self.assertEqual(tablet.price_for(3), Decimal("4"))  # ว่าง = ใช้ราคาระดับ 1

    def test_editing_keeps_units_it_was_given_and_removes_the_rest(self):
        product = save_product(product_data(units=[unit_data("แผง", 10), unit_data("กล่อง", 100, ("380",))]))
        strip = product.units.get(name="แผง")
        updated = save_product(
            product_data(trade_name="Ibuprofen", units=[unit_data("แผง", 10, ("45",), id=strip.pk)]),
            product=product,
        )
        self.assertEqual([u.name for u in updated.units.all()], ["แผง"])
        self.assertEqual(updated.units.get().price1, Decimal("45"))

    def test_a_unit_with_history_cannot_be_dropped(self):
        product = make_product(trade_name="Amox")
        strip = make_unit(product, "แผง", 10)
        receive(strip, [("A1", 300, 2)])
        with self.assertRaises(ProductError) as ctx:
            save_product(product_data(trade_name="Amox", units=[unit_data("กล่อง", 100, ("380",))]), product=product)
        self.assertIn("ลบไม่ได้", ctx.exception.message)
        self.assertTrue(ProductUnit.objects.filter(pk=strip.pk).exists())

    def test_refuses_a_barcode_or_code_already_used_by_another_drug(self):
        other = make_product(trade_name="Other")
        make_unit(other, "แผง", 10, barcode="200042")
        other.code = "X-1"
        other.save()
        with self.assertRaises(ProductError) as ctx:
            save_product(product_data(units=[unit_data(barcode="200042")]))
        self.assertIn("ใช้อยู่กับ", ctx.exception.message)
        with self.assertRaises(ProductError) as ctx:
            save_product(product_data(code="X-1"))
        self.assertIn("รหัสสินค้า", ctx.exception.message)
        self.assertEqual(Product.objects.count(), 1)  # ไม่มีอะไรถูกบันทึกค้างไว้

    def test_refuses_empty_names_missing_prices_and_duplicate_units(self):
        for data, expected in [
            (product_data(trade_name=" "), "ชื่อการค้า"),
            (product_data(base_unit=""), "หน่วยเล็กสุด"),
            (product_data(category="ยาดี"), "ประเภท"),
            (product_data(units=[]), "อย่างน้อย 1 หน่วย"),
            (product_data(units=[unit_data(prices=(None,))]), "ราคาระดับ 1"),
            (product_data(units=[unit_data(prices=("-5",))]), "ติดลบ"),
            (product_data(units=[unit_data("แผง"), unit_data("แผง")]), "ซ้ำกัน"),
            (product_data(units=[unit_data(factor=0)]), "จำนวนหน่วยเล็กสุด"),
        ]:
            with self.subTest(expected=expected), self.assertRaises(ProductError) as ctx:
                save_product(data)
            self.assertIn(expected, ctx.exception.message)
        self.assertFalse(Product.objects.exists())

    def test_allergen_groups_can_be_set_by_hand(self):
        group = Allergen.objects.create(name="NSAIDs", keywords="ibuprofen")
        product = save_product(product_data(allergen_ids=[group.pk]))
        self.assertEqual([a.name for a in product.allergens.all()], ["NSAIDs"])


class ManageApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password="x", is_staff=True)
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.owner)
        self.client.get("/api/auth/csrf")

    def send(self, method, path, data=None):
        return getattr(self.client, method)(
            path, json.dumps(data or {}), content_type="application/json",
            HTTP_X_CSRFTOKEN=self.client.cookies["csrftoken"].value,
        )

    def body(self, **kwargs):
        defaults = {
            "trade_name": "Ibuprofen", "strength": "400 mg", "base_unit": "เม็ด", "category": "dangerous",
            "code": "IBU-400",
            "units": [{"name": "แผง", "factor": 10, "barcode": "200111", "is_default": True,
                       "prices": ["40.00", None, None, None, None]}],
        }
        return {**defaults, **kwargs}

    def test_create_search_open_and_edit(self):
        created = self.send("post", "/api/manage/products", self.body())
        self.assertEqual(created.status_code, 200, created.content)
        product_id = created.json()["id"]
        self.assertEqual(created.json()["units"][0]["prices"][1], None)

        rows = self.client.get("/api/manage/products", {"q": "IBU"}).json()
        self.assertEqual([(r["display_name"], r["code"], r["unit_count"]) for r in rows],
                         [("Ibuprofen 400 mg", "IBU-400", 1)])

        full = self.client.get(f"/api/manage/products/{product_id}").json()
        full["storage_location"] = "ชั้น C3"
        full["units"][0]["prices"] = ["42.00", "40.00", None, None, None]
        saved = self.send("put", f"/api/manage/products/{product_id}", full)
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(saved.json()["storage_location"], "ชั้น C3")
        self.assertEqual(ProductUnit.objects.get().price2, Decimal("40.00"))

    def test_bad_data_comes_back_as_a_readable_message(self):
        response = self.send("post", "/api/manage/products", self.body(units=[]))
        self.assertEqual(response.status_code, 400)
        self.assertIn("หน่วยขาย", response.json()["detail"])

    def test_staff_only(self):
        self.client.force_login(User.objects.create_user("staff", password="x"))
        self.assertEqual(self.client.get("/api/manage/products").status_code, 403)
        self.assertEqual(self.send("post", "/api/manage/products", self.body()).status_code, 403)


class WorklistTests(TestCase):
    """รายการงานหลังนำเข้าไฟล์: อะไรยังขาด เสนอประเภทให้ไหม และยิงบาร์โค้ดทีละตัว"""

    def setUp(self):
        self.owner = User.objects.create_user("owner", password="x", is_staff=True)
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.owner)
        self.client.get("/api/auth/csrf")

    def send(self, method, path, data=None):
        return getattr(self.client, method)(
            path, json.dumps(data or {}), content_type="application/json",
            HTTP_X_CSRFTOKEN=self.client.cookies["csrftoken"].value,
        )

    def imported(self, trade_name="Amoxil 500mg", **kwargs):
        """ยาแบบที่เพิ่งนำเข้าจากไฟล์: ไม่มีชื่อสามัญ ไม่มีบาร์โค้ด หน่วยเดียว และยังไม่ได้ตรวจประเภท"""
        defaults = dict(category=Product.Category.DANGEROUS, base_unit="แผง", needs_review=True)
        product = Product.objects.create(trade_name=trade_name, **{**defaults, **kwargs})
        ProductUnit.objects.create(product=product, name="แผง", factor=1, price1=40)
        return product

    def test_every_gap_is_counted_and_filterable(self):
        self.imported()
        gaps = {gap["key"]: gap["count"] for gap in self.client.get("/api/manage/gaps").json()}
        self.assertEqual(gaps, {"review": 1, "barcode": 1, "generic": 1, "unit": 1})

        rows = self.client.get("/api/manage/products", {"missing": "barcode"}).json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(sorted(rows[0]["missing"]), ["barcode", "generic", "review", "unit"])

    def test_a_drug_whose_name_gives_it_away_comes_with_a_suggestion(self):
        self.imported(trade_name="Gauze 4x4 ซ้อนพับ")
        row = self.client.get("/api/manage/products", {"missing": "review"}).json()[0]
        self.assertEqual(row["suggestion"]["category"], Product.Category.GENERAL)
        self.assertEqual(row["suggestion"]["term"], "gauze")

        # ชื่อการค้าล้วนไม่มีข้อเสนอ และต้องไม่เดาส่งเดช
        self.imported(trade_name="Icolid")
        rows = {r["display_name"]: r["suggestion"] for r in self.client.get("/api/manage/products", {"missing": "review"}).json()}
        self.assertIsNone(rows["Icolid"])

    def test_accepting_the_category_clears_the_review_flag(self):
        product = self.imported(trade_name="Gauze 4x4")
        response = self.send("put", f"/api/manage/products/{product.pk}/category", {"category": "general"})
        self.assertEqual(response.status_code, 200, response.content)
        product.refresh_from_db()
        self.assertEqual((product.category, product.needs_review), (Product.Category.GENERAL, False))
        self.assertEqual(self.client.get("/api/manage/products", {"missing": "review"}).json(), [])

        bad = self.send("put", f"/api/manage/products/{product.pk}/category", {"category": "ยาดี"})
        self.assertEqual(bad.status_code, 400)

    def test_scanning_a_barcode_into_one_unit(self):
        product = self.imported()
        unit = product.units.get()
        response = self.send("put", f"/api/manage/units/{unit.pk}/barcode", {"barcode": " 8850123456789 "})
        self.assertEqual(response.status_code, 200, response.content)
        unit.refresh_from_db()
        self.assertEqual(unit.barcode, "8850123456789")
        self.assertNotIn("barcode", self.client.get("/api/manage/products").json()[0]["missing"])

        # ยิงโค้ดเดิมใส่ยาตัวอื่นต้องไม่ผ่าน ไม่งั้นสแกนขายแล้วได้ผิดตัว
        other = self.imported(trade_name="Tylenol 500mg")
        clash = self.send("put", f"/api/manage/units/{other.units.get().pk}/barcode", {"barcode": "8850123456789"})
        self.assertEqual(clash.status_code, 400)
        self.assertIn("Amoxil", clash.json()["detail"])

    def test_opening_a_drug_and_saving_it_counts_as_reviewed(self):
        product = self.imported()
        full = self.client.get(f"/api/manage/products/{product.pk}").json()
        self.assertTrue(full["needs_review"])
        saved = self.send("put", f"/api/manage/products/{product.pk}", full)
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertFalse(saved.json()["needs_review"])
