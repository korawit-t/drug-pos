import json
from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from accounts.models import User

from .models import Lot, Product, ProductUnit, Purchase, PurchaseItem, Supplier
from .services import (
    PurchaseData,
    PurchaseLine,
    StockError,
    allocate_fefo,
    delete_draft,
    last_costs,
    post_purchase,
    save_purchase,
    stock_mismatches,
)


def make_product(**kwargs) -> Product:
    defaults = dict(trade_name="Amoxicillin", strength="500 mg", category=Product.Category.DANGEROUS, base_unit="แคปซูล")
    return Product.objects.create(**{**defaults, **kwargs})


def make_unit(product, name="แผง", factor=10, **prices) -> ProductUnit:
    return ProductUnit.objects.create(product=product, name=name, factor=factor, price1=prices.pop("price1", 40), **prices)


def receive(product_unit, lots, user=None, opening=False, received_date=None):
    """lots: [(lot_no, days_to_expiry, qty_in_unit)]"""
    today = timezone.localdate()
    purchase = Purchase.objects.create(
        is_opening_balance=opening,
        supplier=None if opening else Supplier.objects.get_or_create(name="ผู้ขายทดสอบ")[0],
        received_date=received_date or today,
    )
    for lot_no, days, qty in lots:
        PurchaseItem.objects.create(
            purchase=purchase, unit=product_unit, qty=qty, lot_no=lot_no,
            expiry_date=today + timedelta(days=days), unit_cost=Decimal("20"),
        )
    return post_purchase(purchase, user)


class PriceLevelTests(TestCase):
    def test_empty_levels_fall_back_to_level_one(self):
        unit = make_unit(make_product(), price1=Decimal("40"), price2=Decimal("36"))
        self.assertEqual(unit.price_for(1), Decimal("40"))
        self.assertEqual(unit.price_for(2), Decimal("36"))
        self.assertEqual(unit.price_for(5), Decimal("40"))


class ReceivingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("admin", password="x")
        self.product = make_product()
        self.box = make_unit(self.product, "กล่อง", 100)

    def test_posting_creates_lots_in_base_units_and_ledger_rows(self):
        receive(self.box, [("A1", 300, 2)], self.user)
        lot = Lot.objects.get(lot_no="A1")
        self.assertEqual(lot.qty_on_hand, 200)
        self.assertEqual(lot.cost_per_base, Decimal("0.2000"))
        self.assertEqual(lot.movements.get().qty, 200)
        self.assertEqual(stock_mismatches(), [])

    def test_same_lot_received_twice_adds_up(self):
        receive(self.box, [("A1", 300, 1)], self.user)
        receive(self.box, [("A1", 300, 1)], self.user)
        self.assertEqual(Lot.objects.get(lot_no="A1").qty_on_hand, 200)

    def test_cannot_post_twice(self):
        purchase = receive(self.box, [("A1", 300, 1)], self.user)
        with self.assertRaises(StockError):
            post_purchase(purchase, self.user)
        self.assertEqual(Lot.objects.get().qty_on_hand, 100)

    def test_expired_stock_cannot_be_received(self):
        with self.assertRaises(StockError):
            receive(self.box, [("OLD", -1, 1)], self.user)
        self.assertFalse(Lot.objects.exists())

    def test_opening_balance_may_include_expired_stock(self):
        receive(self.box, [("OLD", -1, 1)], self.user, opening=True)
        self.assertEqual(Lot.objects.get().qty_on_hand, 100)


class FefoTests(TestCase):
    def setUp(self):
        self.product = make_product()
        self.strip = make_unit(self.product)
        receive(self.strip, [("LATE", 400, 5), ("SOON", 100, 1), ("GONE", -3, 3)], opening=True)

    def test_takes_earliest_expiry_first_and_spans_lots(self):
        allocations = allocate_fefo(self.product, 25)
        self.assertEqual([(a.lot.lot_no, a.qty) for a in allocations], [("SOON", 10), ("LATE", 15)])

    def test_expired_lots_are_never_allocated(self):
        with self.assertRaises(StockError) as ctx:
            allocate_fefo(self.product, 61)
        self.assertIn("มี 60", ctx.exception.message)
        self.assertIn("หมดอายุอีก 30", ctx.exception.message)

    def test_lot_expiring_today_is_still_sellable(self):
        product = make_product(trade_name="Other")
        unit = make_unit(product)
        receive(unit, [("TODAY", 0, 1)], opening=True)
        self.assertEqual(allocate_fefo(product, 10)[0].lot.lot_no, "TODAY")


class SavePurchaseTests(TestCase):
    """The React receiving screen: drafts, posting, and the checks in between."""

    def setUp(self):
        self.user = User.objects.create_user("staff", password="x")
        self.supplier = Supplier.objects.create(name="ผู้ขาย ก")
        self.product = make_product()
        self.box = make_unit(self.product, "กล่อง", 100)
        self.today = timezone.localdate()

    def data(self, lines, **kwargs):
        defaults = dict(received_date=self.today, supplier_id=self.supplier.pk, invoice_no="IV-1")
        return PurchaseData(lines=lines, **{**defaults, **kwargs})

    def line(self, lot="A1", days=300, qty=2, cost="250"):
        expiry = self.today + timedelta(days=days) if days is not None else None
        return PurchaseLine(self.box.pk, qty, lot, expiry, Decimal(cost) if cost is not None else None)

    def test_draft_can_be_incomplete_and_touches_no_stock(self):
        purchase = save_purchase(self.data([self.line(lot="", days=None)]), self.user)
        self.assertEqual(purchase.status, Purchase.Status.DRAFT)
        self.assertEqual(purchase.created_by, self.user)
        self.assertFalse(Lot.objects.exists())

    def test_posting_needs_lot_and_expiry_and_saves_nothing_on_failure(self):
        with self.assertRaises(StockError) as ctx:
            save_purchase(self.data([self.line(), self.line(lot="", days=None)]), self.user, post=True)
        self.assertIn("รายการที่ 2", ctx.exception.message)
        self.assertFalse(Purchase.objects.exists())
        self.assertFalse(Lot.objects.exists())

    def test_update_draft_then_post(self):
        draft = save_purchase(self.data([self.line(lot="")]), self.user)
        posted = save_purchase(self.data([self.line(lot="A1", qty=3)]), self.user, purchase=draft, post=True)
        self.assertEqual(posted.pk, draft.pk)
        self.assertEqual(posted.status, Purchase.Status.POSTED)
        self.assertEqual(posted.items.count(), 1)
        self.assertEqual(Lot.objects.get(lot_no="A1").qty_on_hand, 300)
        self.assertEqual(stock_mismatches(), [])

    def test_posted_receipt_cannot_be_edited_or_deleted(self):
        posted = save_purchase(self.data([self.line()]), self.user, post=True)
        with self.assertRaises(StockError):
            save_purchase(self.data([self.line(qty=5)]), self.user, purchase=posted)
        with self.assertRaises(StockError):
            delete_draft(posted)
        self.assertEqual(Lot.objects.get().qty_on_hand, 200)

    def test_same_invoice_from_same_supplier_is_rejected(self):
        save_purchase(self.data([self.line()]), self.user, post=True)
        with self.assertRaises(StockError):
            save_purchase(self.data([self.line(lot="B2")]), self.user)

    def test_supplier_required_unless_opening_balance(self):
        with self.assertRaises(StockError):
            save_purchase(self.data([self.line()], supplier_id=None), self.user, post=True)
        opening = save_purchase(
            self.data([self.line(days=-5)], supplier_id=None, invoice_no="", is_opening_balance=True),
            self.user, post=True,
        )
        self.assertEqual(opening.status, Purchase.Status.POSTED)

    def test_empty_cost_is_kept_in_drafts_and_required_to_post(self):
        draft = save_purchase(self.data([self.line(cost=None)]), self.user)
        self.assertIsNone(draft.items.get().unit_cost)
        with self.assertRaises(StockError) as ctx:
            save_purchase(self.data([self.line(cost=None)]), self.user, purchase=draft, post=True)
        self.assertIn("ราคาทุน", ctx.exception.message)
        opening = save_purchase(
            self.data([self.line(lot="OB", cost=None)], supplier_id=None, invoice_no="", is_opening_balance=True),
            self.user, post=True,
        )
        self.assertEqual(opening.status, Purchase.Status.POSTED)
        self.assertEqual(Lot.objects.get(lot_no="OB").cost_per_base, Decimal("0"))

    def test_received_date_cannot_be_in_the_future(self):
        with self.assertRaises(StockError):
            save_purchase(self.data([self.line()], received_date=self.today + timedelta(days=1)), self.user)

    def test_last_costs_come_from_the_latest_posted_supplier_receipt(self):
        save_purchase(self.data([self.line(cost="240")], invoice_no="IV-1"), self.user, post=True)
        save_purchase(self.data([self.line(lot="B2", cost="255.50")], invoice_no="IV-2"), self.user, post=True)
        save_purchase(self.data([self.line(lot="C3", cost="999")], invoice_no="IV-3"), self.user)  # draft
        self.assertEqual(last_costs([self.box.pk]), {self.box.pk: Decimal("255.50")})


class ReceivingApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("staff", password="x")
        self.supplier = Supplier.objects.create(name="ผู้ขาย ก")
        self.box = make_unit(make_product(), "กล่อง", 100, barcode="200009")
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.client.get("/api/auth/csrf")

    def send(self, method, path, data=None):
        return getattr(self.client, method)(
            path, json.dumps(data or {}), content_type="application/json",
            HTTP_X_CSRFTOKEN=self.client.cookies["csrftoken"].value,
        )

    def test_draft_edit_post_and_report(self):
        today = timezone.localdate()
        body = {
            "received_date": str(today), "supplier_id": self.supplier.pk, "invoice_no": "IV-9",
            "lines": [{"unit_id": self.box.pk, "qty": 2, "lot_no": "", "unit_cost": "250.00"}],
        }
        response = self.send("post", "/api/purchases", body)
        self.assertEqual(response.status_code, 200, response.content)
        draft = response.json()
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(draft["items"][0]["product"]["display_name"], "Amoxicillin 500 mg")
        self.assertEqual(self.client.get("/api/purchases").json()[0]["id"], draft["id"])

        # Posting an incomplete line is refused and changes nothing.
        response = self.send("put", f"/api/purchases/{draft['id']}", {**body, "post": True})
        self.assertEqual(response.status_code, 400)
        self.assertIn("lot", response.json()["detail"])

        body["lines"][0].update(lot_no="A7", expiry_date=str(today + timedelta(days=400)))
        response = self.send("put", f"/api/purchases/{draft['id']}", {**body, "post": True})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], "posted")
        self.assertEqual(Decimal(response.json()["total_cost"]), Decimal("500.00"))
        self.assertEqual(Lot.objects.get(lot_no="A7").qty_on_hand, 200)

        self.assertEqual(self.send("delete", f"/api/purchases/{draft['id']}").status_code, 400)
        self.assertContains(self.client.get("/reports/ky9/"), "A7")
        costs = self.client.get("/api/purchases/last-costs", {"unit_ids": str(self.box.pk)}).json()
        self.assertEqual(Decimal(costs[str(self.box.pk)]), Decimal("250.00"))
