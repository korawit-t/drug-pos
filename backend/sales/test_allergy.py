import json

from django.test import Client, TestCase

from accounts.models import PinAttempt
from inventory.allergy import AllergyIndex, allergy_alerts
from inventory.models import Allergen
from inventory.tests import make_product

from .models import Customer, CustomerAllergy
from .services import CartLine, SaleError, checkout, sign_dispense
from .tests import SaleTestCase


class AllergyMatchingTests(TestCase):
    """Uses the default drug groups created by the inventory migrations."""

    def setUp(self):
        self.customer = Customer.objects.create(name="ทดสอบ")
        self.index = AllergyIndex()

    def product(self, trade_name, generic_name=""):
        return make_product(trade_name=trade_name, generic_name=generic_name, strength="")

    def alerts(self, product, **allergy):
        record = CustomerAllergy.objects.create(customer=self.customer, **allergy)
        found = allergy_alerts([record], [product], self.index).get(product.pk, [])
        record.delete()
        return found

    def test_free_text_allergy_matches_another_drug_of_the_same_group(self):
        [alert] = self.alerts(self.product("Amoxicillin", "Amoxicillin trihydrate"), substance="Penicillin (ผื่นลมพิษ)")
        self.assertEqual(alert.level, "direct")
        self.assertIn("Penicillins", alert.message)

    def test_related_group_is_a_cross_reactivity_warning(self):
        [alert] = self.alerts(self.product("Cephalexin", "Cephalexin monohydrate"), substance="Penicillin")
        self.assertEqual(alert.level, "cross")
        [alert] = self.alerts(self.product("Ibuprofen", "Ibuprofen"), substance="Aspirin")
        self.assertEqual(alert.level, "cross")

    def test_keywords_match_whole_words_only(self):
        self.assertEqual(self.alerts(self.product("Ventolin", "Salbutamol sulfate"), substance="sulfa"), [])
        [alert] = self.alerts(self.product("Bactrim", "Sulfamethoxazole + Trimethoprim"), substance="sulfa")
        self.assertEqual(alert.level, "direct")

    def test_thai_names_match_inside_thai_text(self):
        [alert] = self.alerts(self.product("Tylenol", "Paracetamol"), substance="แพ้พาราเซตามอล")
        self.assertEqual(alert.level, "direct")

    def test_drug_outside_every_group_still_matches_by_name(self):
        [alert] = self.alerts(self.product("Tramadol", "Tramadol HCl"), substance="Tramadol")
        self.assertEqual(alert.level, "direct")

    def test_brand_name_needs_an_explicit_group(self):
        brand = self.product("Augmentin")
        self.assertEqual(self.alerts(brand, substance="Penicillin"), [])
        brand.allergens.add(Allergen.objects.get(name__startswith="Penicillins"))
        self.assertEqual(self.alerts(brand, substance="Penicillin")[0].level, "direct")

    def test_group_picked_without_text(self):
        group = Allergen.objects.get(name__startswith="NSAIDs")
        self.assertEqual(self.alerts(self.product("Voltaren", "Diclofenac sodium"), allergen=group)[0].level, "direct")

    def test_unrelated_drug_does_not_alert(self):
        self.assertEqual(self.alerts(self.product("Paracetamol", "Paracetamol"), substance="Penicillin"), [])


class AllergyCheckoutTests(SaleTestCase):
    def setUp(self):
        super().setUp()
        self.customer = Customer.objects.create(name="แพ้เพนิซิลลิน")
        CustomerAllergy.objects.create(customer=self.customer, substance="Penicillin", severity="severe")

    def with_allergy(self, unit, qty, note, customer=None):
        customer = customer or self.customer
        token = sign_dispense(self.pharmacist, self.bill, unit.pk, qty, "", allergy=(customer.pk, note))
        return CartLine(unit.pk, qty, "", token, allergy_note=note)

    def test_plain_confirmation_is_not_enough_when_the_customer_is_allergic(self):
        with self.assertRaises(SaleError) as ctx:
            checkout(self.request([self.approved(self.amox_strip, 1)], customer_id=self.customer.pk), self.cashier)
        self.assertEqual(ctx.exception.status, 409)
        self.assertIn("แพ้ยา", ctx.exception.message)

    def test_pharmacist_reason_is_saved_with_the_alert(self):
        line = self.with_allergy(self.amox_strip, 1, "ลูกค้ายืนยันเคยใช้แล้วไม่แพ้")
        sale = checkout(self.request([line], customer_id=self.customer.pk), self.cashier)
        item = sale.items.get()
        self.assertIn("Penicillins", item.allergy_alert)
        self.assertEqual(item.allergy_note, "ลูกค้ายืนยันเคยใช้แล้วไม่แพ้")
        self.assertEqual(item.confirmed_by, self.pharmacist)

    def test_changing_the_reason_after_confirmation_is_refused(self):
        line = self.with_allergy(self.amox_strip, 1, "เหตุผลเดิม")
        line.allergy_note = "เหตุผลใหม่"
        with self.assertRaises(SaleError):
            checkout(self.request([line], customer_id=self.customer.pk), self.cashier)

    def test_confirmation_for_another_customer_is_refused(self):
        other = Customer.objects.create(name="อีกคน")
        CustomerAllergy.objects.create(customer=other, substance="Amoxicillin")
        line = self.with_allergy(self.amox_strip, 1, "ตรวจแล้ว", customer=other)
        with self.assertRaises(SaleError):
            checkout(self.request([line], customer_id=self.customer.pk), self.cashier)

    def test_household_remedy_needs_the_pharmacist_when_it_matches_an_allergy(self):
        CustomerAllergy.objects.create(customer=self.customer, substance="Paracetamol")
        with self.assertRaises(SaleError):
            checkout(self.request([CartLine(self.para_strip.pk, 1)], customer_id=self.customer.pk), self.cashier)
        sale = checkout(
            self.request([self.with_allergy(self.para_strip, 1, "แพ้เล็กน้อย แพทย์ให้ใช้ต่อ")],
                         customer_id=self.customer.pk),
            self.cashier,
        )
        self.assertEqual(sale.items.get().confirmed_by, self.pharmacist)

    def test_walk_in_customer_has_no_allergy_checks(self):
        sale = checkout(self.request([self.approved(self.amox_strip, 1)]), self.cashier)
        self.assertEqual(sale.items.get().allergy_alert, "")


class AllergyApiTests(SaleTestCase):
    def setUp(self):
        super().setUp()
        self.customer = Customer.objects.create(name="ลูกค้า API")
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.cashier)
        self.client.get("/api/auth/csrf")

    def post(self, path, data):
        return self.client.post(
            path, json.dumps(data), content_type="application/json",
            HTTP_X_CSRFTOKEN=self.client.cookies["csrftoken"].value,
        )

    def test_record_check_confirm_and_sell(self):
        response = self.post(
            f"/api/customers/{self.customer.pk}/allergies",
            {"substance": "Amoxicillin", "reaction": "ผื่น", "severity": "severe"},
        )
        self.assertEqual(response.status_code, 200, response.content)
        [allergy] = response.json()["allergies"]
        self.assertTrue(allergy["matched"])
        self.assertEqual(allergy["severity_label"], "รุนแรง (เช่น SJS หายใจลำบาก ช็อก)")

        ids = f"{self.amox.pk},{self.para.pk}"
        alerts = self.client.get(f"/api/customers/{self.customer.pk}/allergy-check", {"product_ids": ids}).json()
        self.assertEqual(list(alerts["alerts"]), [str(self.amox.pk)])

        approval = {
            "pharmacist_id": self.pharmacist.pk, "pin": "1234", "client_uuid": str(self.bill),
            "customer_id": self.customer.pk,
            "lines": [{"key": "a", "unit_id": self.amox_strip.pk, "qty": 1, "dosage_text": ""}],
        }
        self.assertEqual(self.post("/api/approvals/dispense", approval).status_code, 400)
        self.assertFalse(PinAttempt.objects.exists())  # a missing reason isn't a PIN attempt

        approval["lines"][0]["allergy_note"] = "เภสัชกรซักประวัติแล้ว เป็นผื่นจากอาหาร"
        response = self.post("/api/approvals/dispense", approval)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["allergy_keys"], ["a"])

        response = self.post("/api/sales", {
            "client_uuid": str(self.bill), "payment_method": "cash", "cash_received": "100",
            "customer_id": self.customer.pk,
            "lines": [{
                "unit_id": self.amox_strip.pk, "qty": 1, "dosage_text": "",
                "approval": response.json()["tokens"]["a"],
                "allergy_note": "เภสัชกรซักประวัติแล้ว เป็นผื่นจากอาหาร",
            }],
        })
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("Penicillins", response.json()["items"][0]["allergy_alert"])

    def test_allergy_needs_a_drug_or_a_group(self):
        response = self.post(f"/api/customers/{self.customer.pk}/allergies", {"reaction": "ผื่น"})
        self.assertEqual(response.status_code, 400)

    def test_customer_payload_lists_allergies(self):
        CustomerAllergy.objects.create(customer=self.customer, substance="ยาแก้อักเสบสีเหลือง")
        [allergy] = self.client.get(f"/api/customers/{self.customer.pk}").json()["allergies"]
        self.assertFalse(allergy["matched"])  # vague text: shown, but can't be matched to a group
