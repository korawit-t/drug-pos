import json
import uuid
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from accounts.models import PinAttempt, User
from accounts.tests import make_pharmacist
from inventory.models import Lot, Product
from inventory.services import stock_mismatches
from inventory.tests import make_product, make_unit, receive

from .models import Sale
from .services import CartLine, CheckoutRequest, SaleError, checkout, daily_summary, sign_dispense, void_sale


class SaleTestCase(TestCase):
    def setUp(self):
        self.cashier = User.objects.create_user("staff", password="staff-pass")
        self.pharmacist = make_pharmacist(pin="1234")
        self.para = make_product(trade_name="Paracetamol", category=Product.Category.HOUSEHOLD, base_unit="เม็ด")
        self.para_strip = make_unit(self.para, price1=Decimal("15"), price2=Decimal("13"), barcode="200001")
        receive(self.para_strip, [("P1", 300, 10)], opening=True)
        self.amox = make_product()  # ยาอันตราย
        self.amox_strip = make_unit(self.amox, price1=Decimal("40"), barcode="200002")
        receive(self.amox_strip, [("A1", 100, 1), ("A2", 400, 5)], opening=True)
        self.bill = uuid.uuid4()

    def request(self, lines, **kwargs):
        defaults = dict(client_uuid=self.bill, payment_method="cash", cash_received=Decimal("1000"))
        return CheckoutRequest(lines=lines, **{**defaults, **kwargs})

    def approved(self, unit, qty, dosage="", bill=None):
        token = sign_dispense(self.pharmacist, bill or self.bill, unit.pk, qty, dosage)
        return CartLine(unit.pk, qty, dosage, token)


class CheckoutTests(SaleTestCase):
    def test_cash_sale_takes_stock_fefo_and_gives_change(self):
        sale = checkout(
            self.request(
                [CartLine(self.para_strip.pk, 2), self.approved(self.amox_strip, 2, "วันละ 3 ครั้ง")],
                cash_received=Decimal("200"),
            ),
            self.cashier,
        )
        self.assertEqual(sale.total, Decimal("110.00"))
        self.assertEqual(sale.change, Decimal("90.00"))
        amox = sale.items.get(product=self.amox)
        self.assertEqual(amox.confirmed_by, self.pharmacist)
        self.assertEqual(amox.dosage_text, "วันละ 3 ครั้ง")
        self.assertEqual([(a.lot.lot_no, a.qty) for a in amox.allocations.all()], [("A1", 10), ("A2", 10)])
        self.assertEqual(stock_mismatches(), [])

    def test_price_level_applies_with_fallback_to_level_one(self):
        sale = checkout(
            self.request([CartLine(self.para_strip.pk, 1), self.approved(self.amox_strip, 1)], price_level=2),
            self.cashier,
        )
        prices = {item.product_id: item.unit_price for item in sale.items.all()}
        self.assertEqual(prices[self.para.pk], Decimal("13"))
        self.assertEqual(prices[self.amox.pk], Decimal("40"))

    def test_dangerous_drug_needs_pharmacist(self):
        with self.assertRaises(SaleError):
            checkout(self.request([CartLine(self.amox_strip.pk, 1)]), self.cashier)
        self.assertFalse(Sale.objects.exists())

    def test_changing_qty_after_confirmation_needs_new_confirmation(self):
        line = self.approved(self.amox_strip, 1)
        line.qty = 2
        with self.assertRaises(SaleError):
            checkout(self.request([line]), self.cashier)

    def test_changing_label_after_confirmation_needs_new_confirmation(self):
        line = self.approved(self.amox_strip, 1, "วันละ 3 ครั้ง")
        line.dosage_text = "วันละ 4 ครั้ง"
        with self.assertRaises(SaleError):
            checkout(self.request([line]), self.cashier)

    def test_confirmation_only_counts_for_its_own_bill(self):
        line = self.approved(self.amox_strip, 1, bill=uuid.uuid4())
        with self.assertRaises(SaleError):
            checkout(self.request([line]), self.cashier)

    def test_ky11_drug_needs_buyer_name(self):
        syrup = make_product(trade_name="Syrup", in_ky11_list=True, base_unit="ขวด")
        bottle = make_unit(syrup, "ขวด", 1, price1=Decimal("60"))
        receive(bottle, [("S1", 300, 5)], opening=True)
        with self.assertRaises(SaleError):
            checkout(self.request([self.approved(bottle, 1)]), self.cashier)
        sale = checkout(self.request([self.approved(bottle, 1)], buyer_name="นาย ก"), self.cashier)
        self.assertEqual(sale.buyer_name, "นาย ก")
        self.assertTrue(sale.items.get().in_ky11_list)

    def test_special_controlled_needs_prescription(self):
        pred = make_product(trade_name="Prednisolone", category=Product.Category.SPECIAL_CONTROLLED, base_unit="เม็ด")
        strip = make_unit(pred, price1=Decimal("20"))
        receive(strip, [("PD1", 300, 5)], opening=True)
        with self.assertRaises(SaleError):
            checkout(self.request([self.approved(strip, 1)]), self.cashier)
        buddhist_year_date = timezone.localdate().replace(year=timezone.localdate().year + 543)
        with self.assertRaises(SaleError):
            checkout(
                self.request([self.approved(strip, 1)], rx_prescriber="นพ.ข", rx_facility="รพ.ค",
                             rx_date=buddhist_year_date),
                self.cashier,
            )
        sale = checkout(
            self.request([self.approved(strip, 1)], rx_prescriber="นพ.ข", rx_facility="รพ.ค"), self.cashier
        )
        self.assertTrue(sale.is_prescription)

    def test_not_enough_cash(self):
        with self.assertRaises(SaleError):
            checkout(self.request([CartLine(self.para_strip.pk, 1)], cash_received=Decimal("10")), self.cashier)

    def test_transfer_has_no_change(self):
        sale = checkout(
            self.request([CartLine(self.para_strip.pk, 1)], payment_method="transfer", cash_received=None),
            self.cashier,
        )
        self.assertIsNone(sale.change)

    def test_not_enough_stock_rolls_back_the_whole_bill(self):
        with self.assertRaises(SaleError):
            checkout(self.request([CartLine(self.para_strip.pk, 1), CartLine(self.para_strip.pk, 10)]), self.cashier)
        self.assertFalse(Sale.objects.exists())
        self.assertEqual(Lot.objects.get(lot_no="P1").qty_on_hand, 100)

    def test_same_bill_submitted_twice_is_saved_once(self):
        req = self.request([CartLine(self.para_strip.pk, 1)])
        first = checkout(req, self.cashier)
        second = checkout(req, self.cashier)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Lot.objects.get(lot_no="P1").qty_on_hand, 90)

    def test_bill_numbers_run_per_day(self):
        first = checkout(self.request([CartLine(self.para_strip.pk, 1)]), self.cashier)
        second = checkout(self.request([CartLine(self.para_strip.pk, 1)], client_uuid=uuid.uuid4()), self.cashier)
        prefix = timezone.localdate().strftime("%y%m%d")
        self.assertEqual(first.number, f"{prefix}-0001")
        self.assertEqual(second.number, f"{prefix}-0002")


class VoidTests(SaleTestCase):
    def test_void_returns_stock_to_the_same_lots(self):
        sale = checkout(self.request([self.approved(self.amox_strip, 2)]), self.cashier)
        self.assertEqual(Lot.objects.get(lot_no="A1").qty_on_hand, 0)
        void_sale(sale, self.pharmacist, "ลูกค้าเปลี่ยนใจ")
        self.assertEqual(Lot.objects.get(lot_no="A1").qty_on_hand, 10)
        self.assertEqual(Lot.objects.get(lot_no="A2").qty_on_hand, 50)
        sale.refresh_from_db()
        self.assertEqual(sale.status, Sale.Status.VOIDED)
        self.assertEqual(stock_mismatches(), [])

    def test_cannot_void_twice(self):
        sale = checkout(self.request([CartLine(self.para_strip.pk, 1)]), self.cashier)
        void_sale(sale, self.pharmacist, "ทดสอบ")
        with self.assertRaises(SaleError):
            void_sale(sale, self.pharmacist, "ทดสอบ")

    def test_daily_summary_excludes_voided_bills(self):
        kept = checkout(self.request([CartLine(self.para_strip.pk, 1)]), self.cashier)
        voided = checkout(
            self.request([CartLine(self.para_strip.pk, 2)], client_uuid=uuid.uuid4(), payment_method="transfer",
                         cash_received=None),
            self.cashier,
        )
        void_sale(voided, self.pharmacist, "ทดสอบ")
        summary = daily_summary(timezone.localdate())
        self.assertEqual(summary["count"], 1)
        self.assertEqual(summary["total"], kept.total)
        self.assertEqual(summary["transfer"], Decimal("0.00"))


class ApiFlowTests(SaleTestCase):
    """The same flow the React counter uses, over HTTP with CSRF enforced."""

    def setUp(self):
        super().setUp()
        self.client = Client(enforce_csrf_checks=True)
        self.client.get("/api/auth/csrf")

    def post(self, path, data):
        return self.client.post(
            path, json.dumps(data), content_type="application/json",
            HTTP_X_CSRFTOKEN=self.client.cookies["csrftoken"].value,
        )

    def login(self):
        response = self.post("/api/auth/login", {"username": "staff", "password": "staff-pass"})
        self.assertEqual(response.status_code, 200, response.content)

    def test_api_requires_login(self):
        self.assertEqual(self.client.get("/api/meta").status_code, 401)

    def test_writes_without_csrf_token_are_rejected(self):
        self.login()
        response = self.client.post("/api/held-bills", json.dumps({"payload": {}}), content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_scan_confirm_pay_and_void(self):
        self.login()
        found = self.client.get("/api/products/search", {"q": "200002"}).json()
        self.assertEqual(found[0]["matched_unit_id"], self.amox_strip.pk)
        self.assertEqual(found[0]["available"], 60)
        self.assertTrue(found[0]["needs_pharmacist"])

        approval = {
            "pharmacist_id": self.pharmacist.pk, "pin": "9999", "client_uuid": str(self.bill),
            "lines": [{"key": "a", "unit_id": self.amox_strip.pk, "qty": 1, "dosage_text": "วันละ 3 ครั้ง"}],
        }
        self.assertEqual(self.post("/api/approvals/dispense", approval).status_code, 403)
        approval["pin"] = "1234"
        response = self.post("/api/approvals/dispense", approval)
        self.assertEqual(response.status_code, 200, response.content)
        token = response.json()["tokens"]["a"]
        self.assertEqual(PinAttempt.objects.filter(success=True).count(), 1)

        response = self.post("/api/sales", {
            "client_uuid": str(self.bill), "payment_method": "cash", "cash_received": "100",
            "lines": [
                {"unit_id": self.amox_strip.pk, "qty": 1, "dosage_text": "วันละ 3 ครั้ง", "approval": token},
                {"unit_id": self.para_strip.pk, "qty": 1},
            ],
        })
        self.assertEqual(response.status_code, 200, response.content)
        sale = response.json()
        self.assertEqual(Decimal(sale["total"]), Decimal("55.00"))
        self.assertEqual(Decimal(sale["change"]), Decimal("45.00"))
        self.assertEqual(sale["items"][0]["confirmed_by"], self.pharmacist.label_name)

        self.assertEqual(self.client.get(f"/print/receipt/{sale['id']}/").status_code, 200)
        labels = self.client.get(f"/print/labels/{sale['id']}/")
        self.assertContains(labels, "วันละ 3 ครั้ง")

        void = {"pharmacist_id": self.pharmacist.pk, "pin": "1234", "reason": "คีย์ผิด"}
        response = self.post(f"/api/sales/{sale['id']}/void", void)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], "voided")
        self.assertEqual(self.client.get("/api/sales/summary").json()["count"], 0)

    def test_reports_render(self):
        self.login()
        for path in ["/reports/", "/reports/ky9/", "/reports/ky11/", "/reports/expiry/"]:
            self.assertEqual(self.client.get(path).status_code, 200, path)
