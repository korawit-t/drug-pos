from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from accounts.models import User

from .models import Lot, Product, ProductUnit, Purchase, PurchaseItem, Supplier
from .services import StockError, allocate_fefo, post_purchase, stock_mismatches


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
