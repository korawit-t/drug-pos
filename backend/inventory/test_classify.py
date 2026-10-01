from django.test import TestCase

from .classify import suggest_category
from .models import Product


class SuggestCategoryTests(TestCase):
    def test_well_known_generics_get_a_suggestion(self):
        cases = [
            ("Amoxicillin 500 mg", "", Product.Category.DANGEROUS),
            ("Coamox", "amoxicillin + clavulanic acid", Product.Category.DANGEROUS),
            ("Sara drop 60mg/15 ml paracetamol", "", Product.Category.HOUSEHOLD),
            ("ผงเกลือแร่ ORS", "", Product.Category.HOUSEHOLD),
            ("Gauze 2x2 ซ้อนพับ", "", Product.Category.GENERAL),
            ("หน้ากากอนามัย", "", Product.Category.GENERAL),
            ("Warfarin 3 mg", "", Product.Category.SPECIAL_CONTROLLED),
        ]
        for trade, generic, expected in cases:
            with self.subTest(trade=trade):
                suggestion = suggest_category(trade, generic)
                self.assertIsNotNone(suggestion, f"{trade} ควรมีข้อเสนอ")
                self.assertEqual(suggestion[0], expected)

    def test_a_trade_name_that_says_nothing_gets_no_suggestion(self):
        # ยาชื่อการค้าล้วน — เดาไม่ได้ และไม่ควรเดา
        for name in ("Icolid", "Sambee 10x10's", "Molax-M", ""):
            self.assertIsNone(suggest_category(name, ""), name)

    def test_english_terms_match_whole_words_only(self):
        self.assertIsNone(suggest_category("Zinc sulfate syrup", ""))
        self.assertEqual(suggest_category("Silverderm", "silver sulfadiazine")[0], Product.Category.DANGEROUS)

    def test_the_reason_comes_back_so_the_screen_can_show_why(self):
        category, term = suggest_category("Buprofen 400 mg", "ibuprofen")
        self.assertEqual((category, term), (Product.Category.DANGEROUS, "ibuprofen"))
