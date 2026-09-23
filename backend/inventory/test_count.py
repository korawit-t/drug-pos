import json
from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from accounts.models import PinAttempt, User

from .models import Lot, StockCount, StockCountItem, StockMovement
from .services import (
    StockCountData,
    StockCountLine,
    StockError,
    allocate_fefo,
    delete_count_draft,
    record_movement,
    save_stock_count,
    stock_mismatches,
)
from .tests import make_product, make_unit, receive


def pharmacist(pin="4821") -> User:
    user = User(username="pharm", role=User.Role.PHARMACIST, display_name="ภก.ทดสอบ")
    user.set_password("รหัสผ่านของร้านนี้")
    user.set_pin(pin)
    user.save()
    return user


class StockCountTests(TestCase):
    """นับสต็อกแล้วปรับยอด — service layer"""

    def setUp(self):
        self.user = User.objects.create_user("staff", password="x")
        self.pharmacist = pharmacist()
        self.product = make_product()
        self.strip = make_unit(self.product)  # แผง x10
        receive(self.strip, [("A1", 300, 20), ("B2", 60, 5)], self.user)  # 200 + 50 แคปซูล
        self.a1 = Lot.objects.get(lot_no="A1")
        self.b2 = Lot.objects.get(lot_no="B2")
        self.today = timezone.localdate()

    def data(self, *lines, **kwargs):
        return StockCountData(counted_date=kwargs.pop("counted_date", self.today), lines=list(lines), **kwargs)

    def line(self, lot, counted, reason="count", note=""):
        return StockCountLine(lot.pk, lot.qty_on_hand, counted, reason, note)

    def post(self, *lines, **kwargs):
        return save_stock_count(
            self.data(*lines, **kwargs), self.user, post=True, approved_by=kwargs.pop("approved_by", self.pharmacist)
        )

    def test_shortage_and_surplus_are_written_to_the_ledger(self):
        count = self.post(
            self.line(self.a1, 195, "damaged", "แตก 5 แคปซูล"),
            self.line(self.b2, 52, "count"),
        )
        self.assertEqual(count.status, StockCount.Status.POSTED)
        self.assertEqual(count.approved_by, self.pharmacist)
        self.assertEqual(count.posted_by, self.user)
        self.a1.refresh_from_db()
        self.b2.refresh_from_db()
        self.assertEqual((self.a1.qty_on_hand, self.b2.qty_on_hand), (195, 52))

        movements = StockMovement.objects.filter(kind=StockMovement.Kind.ADJUST).order_by("id")
        self.assertEqual([m.qty for m in movements], [-5, 2])
        self.assertEqual(movements[0].note, "ชำรุด / แตก / หก: แตก 5 แคปซูล")
        self.assertEqual(movements[0].created_by, self.pharmacist)
        self.assertEqual(stock_mismatches(), [])

    def test_a_count_that_matches_writes_nothing_but_is_kept(self):
        count = self.post(self.line(self.a1, 200))
        self.assertEqual(count.status, StockCount.Status.POSTED)
        self.assertFalse(StockMovement.objects.filter(kind=StockMovement.Kind.ADJUST).exists())
        self.assertIsNone(count.items.get().movement)
        self.assertEqual(Lot.objects.get(pk=self.a1.pk).qty_on_hand, 200)

    def test_expired_stock_can_be_written_off(self):
        expired = receive(self.strip, [("OLD", -10, 3)], self.user, opening=True)
        lot = Lot.objects.get(lot_no="OLD")
        self.post(self.line(lot, 0, "expired", "ทิ้งตามรอบ"))
        self.assertEqual(Lot.objects.get(pk=lot.pk).qty_on_hand, 0)
        self.assertEqual(expired.status, "posted")

    def test_a_sale_while_counting_blocks_the_posting(self):
        lines = [self.line(self.a1, 195, "damaged", "แตก"), self.line(self.b2, 50)]
        allocation = allocate_fefo(self.product, 10)[0]  # FEFO ตัดจาก B2 ที่หมดอายุก่อน
        record_movement(allocation.lot, StockMovement.Kind.SALE, -allocation.qty, user=self.user)

        with self.assertRaises(StockError) as ctx:
            save_stock_count(self.data(*lines), self.user, post=True, approved_by=self.pharmacist)
        self.assertIn("ยอดในระบบเปลี่ยนเป็น 40", ctx.exception.message)
        self.assertIn("lot B2", ctx.exception.message)
        # ทั้งใบไม่ถูกบันทึก แม้แต่รายการที่ยอดยังตรง
        self.assertFalse(StockCount.objects.exists())
        self.assertEqual(Lot.objects.get(pk=self.a1.pk).qty_on_hand, 200)

    def test_a_difference_needs_a_reason_and_other_needs_a_note(self):
        with self.assertRaises(StockError) as ctx:
            self.post(self.line(self.a1, 190, reason=""))
        self.assertIn("สาเหตุ", ctx.exception.message)
        with self.assertRaises(StockError) as ctx:
            self.post(self.line(self.a1, 190, reason="other"))
        self.assertIn("หมายเหตุ", ctx.exception.message)
        self.post(self.line(self.a1, 190, reason="other", note="ยกให้โรงพยาบาล"))
        self.assertEqual(Lot.objects.get(pk=self.a1.pk).qty_on_hand, 190)

    def test_only_a_pharmacist_may_approve(self):
        for approver in (None, self.user):
            with self.assertRaises(StockError) as ctx:
                save_stock_count(
                    self.data(self.line(self.a1, 195, "damaged")), self.user, post=True, approved_by=approver
                )
            self.assertIn("เภสัชกร", ctx.exception.message)
        self.assertEqual(Lot.objects.get(pk=self.a1.pk).qty_on_hand, 200)

    def test_draft_keeps_uncounted_lines_and_touches_no_stock(self):
        draft = save_stock_count(self.data(StockCountLine(self.a1.pk, 200)), self.user)
        self.assertEqual(draft.status, StockCount.Status.DRAFT)
        self.assertIsNone(draft.items.get().counted_qty)
        self.assertIsNone(draft.items.get().difference)
        self.assertEqual(Lot.objects.get(pk=self.a1.pk).qty_on_hand, 200)

        with self.assertRaises(StockError) as ctx:
            save_stock_count(
                self.data(StockCountLine(self.a1.pk, 200)), self.user, count=draft, post=True,
                approved_by=self.pharmacist,
            )
        self.assertIn("ยังไม่ได้กรอก", ctx.exception.message)

        posted = save_stock_count(
            self.data(self.line(self.a1, 198, "lost")), self.user, count=draft, post=True,
            approved_by=self.pharmacist,
        )
        self.assertEqual(posted.pk, draft.pk)
        self.assertEqual(Lot.objects.get(pk=self.a1.pk).qty_on_hand, 198)

    def test_posted_sheet_cannot_be_edited_or_deleted(self):
        count = self.post(self.line(self.a1, 195, "lost"))
        with self.assertRaises(StockError):
            save_stock_count(self.data(self.line(self.a1, 100, "lost")), self.user, count=count)
        with self.assertRaises(StockError):
            delete_count_draft(count)
        self.assertEqual(Lot.objects.get(pk=self.a1.pk).qty_on_hand, 195)

    def test_refuses_negative_counts_duplicate_lots_and_future_dates(self):
        with self.assertRaises(StockError):
            save_stock_count(self.data(StockCountLine(self.a1.pk, 200, -1)), self.user)
        with self.assertRaises(StockError) as ctx:
            save_stock_count(self.data(self.line(self.a1, 200), self.line(self.a1, 199, "lost")), self.user)
        self.assertIn("อยู่ในใบนี้แล้ว", ctx.exception.message)
        with self.assertRaises(StockError):
            save_stock_count(self.data(self.line(self.a1, 200), counted_date=self.today + timedelta(days=1)), self.user)
        self.assertFalse(StockCount.objects.exists())


class StockCountApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("staff", password="x")
        self.pharmacist = pharmacist()
        self.product = make_product()
        self.strip = make_unit(self.product)
        receive(self.strip, [("A1", 300, 20), ("OLD", -5, 1)], self.user, opening=True)
        self.a1 = Lot.objects.get(lot_no="A1")
        self.old = Lot.objects.get(lot_no="OLD")
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.client.get("/api/auth/csrf")

    def send(self, method, path, data=None):
        return getattr(self.client, method)(
            path, json.dumps(data or {}), content_type="application/json",
            HTTP_X_CSRFTOKEN=self.client.cookies["csrftoken"].value,
        )

    def test_lots_for_counting_include_expired_ones(self):
        lots = self.client.get("/api/stock/lots", {"product_id": self.product.pk}).json()
        self.assertEqual([(l["lot_no"], l["qty"], l["expired"]) for l in lots], [("OLD", 10, True), ("A1", 200, False)])
        self.assertEqual(lots[0]["units"], [{"name": "แผง", "factor": 10}])
        expired = self.client.get("/api/stock/lots/expired").json()
        self.assertEqual([l["lot_no"] for l in expired], ["OLD"])

    def test_draft_then_post_with_a_pin(self):
        today = str(timezone.localdate())
        body = {
            "counted_date": today,
            "note": "นับรอบเดือน",
            "lines": [
                {"lot_id": self.a1.pk, "system_qty": 200, "counted_qty": 197, "reason": "damaged", "note": "แตก 3"},
                {"lot_id": self.old.pk, "system_qty": 10, "counted_qty": 0, "reason": "expired"},
            ],
        }
        draft = self.send("post", "/api/stock-counts", body).json()
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(draft["items"][0]["difference"], -3)
        self.assertEqual(draft["items"][0]["reason_label"], "ชำรุด / แตก / หก")
        row = self.client.get("/api/stock-counts").json()[0]
        self.assertEqual((row["item_count"], row["diff_count"]), (2, 2))
        self.assertEqual(Lot.objects.get(pk=self.a1.pk).qty_on_hand, 200)

        # ยืนยันด้วย PIN ผิด: ไม่ปรับอะไรเลย แต่บันทึกความพยายามไว้
        wrong = self.send("put", f"/api/stock-counts/{draft['id']}", {**body, "post": True,
                                                                     "pharmacist_id": self.pharmacist.pk, "pin": "0000"})
        self.assertEqual(wrong.status_code, 403)
        self.assertEqual(Lot.objects.get(pk=self.a1.pk).qty_on_hand, 200)

        ok = self.send("put", f"/api/stock-counts/{draft['id']}", {**body, "post": True,
                                                                   "pharmacist_id": self.pharmacist.pk, "pin": "4821"})
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(ok.json()["status"], "posted")
        self.assertEqual(ok.json()["approved_by"], "ภก.ทดสอบ")
        self.assertEqual(Lot.objects.get(pk=self.a1.pk).qty_on_hand, 197)
        self.assertEqual(Lot.objects.get(pk=self.old.pk).qty_on_hand, 0)

        attempts = PinAttempt.objects.filter(action=PinAttempt.Action.ADJUST).order_by("id")
        self.assertEqual([a.success for a in attempts], [False, True])
        self.assertIn("ปรับยอดสต็อก", attempts[0].detail)

        self.assertEqual(self.send("delete", f"/api/stock-counts/{draft['id']}").status_code, 400)
        report = self.client.get("/reports/adjustments/")
        self.assertContains(report, "แตก 3")
        self.assertContains(report, "ภก.ทดสอบ")

    def test_the_back_office_page_opens_read_only(self):
        # หลังร้านดูใบนับได้อย่างเดียว — ปรับยอดต้องทำที่หน้าจอนับสต็อกเพราะต้องมี PIN
        staff = User.objects.create_superuser("owner", password="x")
        count = save_stock_count(
            StockCountData(
                counted_date=timezone.localdate(),
                lines=[StockCountLine(self.a1.pk, 200, 195, "lost")],
            ),
            self.user,
            post=True,
            approved_by=self.pharmacist,
        )
        self.client.force_login(staff)
        page = self.client.get(f"/admin/inventory/stockcount/{count.pk}/change/")
        self.assertContains(page, "-5")
        self.assertNotContains(page, 'name="items-0-counted_qty"')

    def test_posting_without_a_pharmacist_is_refused(self):
        body = {
            "counted_date": str(timezone.localdate()),
            "lines": [{"lot_id": self.a1.pk, "system_qty": 200, "counted_qty": 195, "reason": "lost"}],
            "post": True,
        }
        response = self.send("post", "/api/stock-counts", body)
        self.assertEqual(response.status_code, 400)
        self.assertIn("เภสัชกร", response.json()["detail"])
        self.assertEqual(Lot.objects.get(pk=self.a1.pk).qty_on_hand, 200)
        self.assertFalse(StockCountItem.objects.exists())
