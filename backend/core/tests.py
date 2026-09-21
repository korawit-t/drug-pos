import datetime
from decimal import Decimal

from django.test import SimpleTestCase

from .promptpay import crc16_ccitt, generate_payload
from .thai import thai_date


class PromptPayTests(SimpleTestCase):
    def test_crc_matches_ccitt_false_check_value(self):
        self.assertEqual(crc16_ccitt(b"123456789"), 0x29B1)

    def test_mobile_number_payload(self):
        payload = generate_payload("081-234-5678", Decimal("170"))
        self.assertTrue(payload.startswith("000201010212"))
        self.assertIn("0016A000000677010111" + "01130066812345678", payload)
        self.assertIn("5406170.00", payload)
        self.assertIn("5802TH" + "5303764", payload)
        body, crc = payload[:-4], payload[-4:]
        self.assertTrue(body.endswith("6304"))
        self.assertEqual(crc, f"{crc16_ccitt(body.encode()):04X}")

    def test_tax_id_and_static_payload(self):
        payload = generate_payload("0105561000000")
        self.assertIn("02130105561000000", payload)
        self.assertTrue(payload.startswith("000201010211"))
        self.assertIn("5303764" + "6304", payload)  # no amount field between currency and CRC


class ThaiDateTests(SimpleTestCase):
    def test_buddhist_year(self):
        d = datetime.date(2026, 9, 21)
        self.assertEqual(thai_date(d), "21/09/2569")
        self.assertEqual(thai_date(d, "long"), "21 ก.ย. 2569")
        self.assertEqual(thai_date(d, "month"), "09/2569")
