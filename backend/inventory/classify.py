"""
เดาประเภทยาจากชื่อ เพื่อ "เสนอ" ให้เภสัชกรกดยืนยัน ไม่ใช่เพื่อตั้งให้เอง

การจัดประเภทยาเป็นเรื่องตามกฎหมาย (ประกาศกระทรวงสาธารณสุข) ไม่ใช่เรื่องที่เดาจากชื่อได้จริง
โค้ดนี้จึงทำได้แค่ลดงานพิมพ์: ยาที่ชื่อสามัญชัดเจนจะมีข้อเสนอขึ้นให้กดรับ ส่วนยาชื่อการค้า
ที่ไม่บอกตัวยาจะไม่มีข้อเสนอ และไม่มีกรณีไหนที่ระบบตั้งประเภทให้เองโดยไม่มีคนยืนยัน

รายการคำด้านล่างเป็นค่าตั้งต้นเหมือนกลุ่มยาแพ้ — ร้านต้องตรวจทานตามประกาศฉบับล่าสุด
"""

import re

from .models import Product

# (ประเภทที่เสนอ, คำที่จับ) — เรียงจากเฉพาะเจาะจงไปกว้าง ตัวแรกที่ตรงคือคำตอบ
HINTS: list[tuple[str, list[str]]] = [
    # ไม่ใช่ยา
    (Product.Category.GENERAL, [
        "gauze", "ก๊อซ", "ผ้าพันแผล", "สำลี", "cotton", "plaster", "พลาสเตอร์", "bandage",
        "mask", "หน้ากาก", "ถุงมือ", "glove", "syringe", "เข็มฉีดยา", "thermometer", "ปรอทวัดไข้",
        "ถุงยาง", "condom", "แปรงสีฟัน", "ยาสีฟัน", "สบู่", "แชมพู", "ยาสระผม", "โลชั่น", "ครีมกันแดด",
        "saline irrigate", "น้ำเกลือล้าง", "alcohol pad", "ที่วัดความดัน",
    ]),
    # ยาสามัญประจำบ้าน (ตรวจกับประกาศ ยาสามัญประจำบ้าน ก่อนใช้จริง)
    (Product.Category.HOUSEHOLD, [
        "paracetamol", "พาราเซตามอล", "ors", "ผงเกลือแร่", "oral rehydration",
        "antacid", "aluminium hydroxide", "magnesium hydroxide", "ยาธาตุ", "ยาลม",
        "calamine", "คาลาไมน์", "povidone-iodine", "povidone iodine", "เบตาดีน",
        "ยาหม่อง", "ยาดม", "น้ำมันเขียว", "ทิงเจอร์ไอโอดีน", "glycerin borax",
        "ยาแก้ไอน้ำดำ", "ยาระบายมะขามแขก", "มะขามแขก", "senna",
    ]),
    # ยาควบคุมพิเศษ — ต้องมีใบสั่งแพทย์
    (Product.Category.SPECIAL_CONTROLLED, [
        "isotretinoin", "warfarin", "digoxin", "insulin", "อินซูลิน", "methotrexate",
        "clozapine", "lithium", "phenobarbital", "carbamazepine", "valproate",
    ]),
    # ยาอันตราย — ยาปฏิชีวนะ ยาแก้อักเสบ สเตียรอยด์ ยาโรคเรื้อรัง ฯลฯ
    (Product.Category.DANGEROUS, [
        # ยาปฏิชีวนะ
        "amoxicillin", "amoxycillin", "ampicillin", "penicillin", "cloxacillin", "dicloxacillin",
        "cephalexin", "cefixime", "cefdinir", "ceftriaxone", "azithromycin", "erythromycin",
        "roxithromycin", "clarithromycin", "clindamycin", "doxycycline", "tetracycline",
        "norfloxacin", "ciprofloxacin", "ofloxacin", "levofloxacin", "metronidazole",
        "co-trimoxazole", "cotrimoxazole", "sulfamethoxazole", "trimethoprim", "fosfomycin",
        "tetracycline", "chloramphenicol", "gentamicin", "neomycin", "mupirocin",
        # แก้ปวด/อักเสบ
        "ibuprofen", "diclofenac", "naproxen", "mefenamic", "meloxicam", "piroxicam",
        "celecoxib", "etoricoxib", "indomethacin", "tramadol", "tolperisone", "orphenadrine",
        # แพ้/หวัด
        "cetirizine", "loratadine", "fexofenadine", "chlorpheniramine", "hydroxyzine",
        "brompheniramine", "dimenhydrinate", "pseudoephedrine", "phenylephrine",
        # สเตียรอยด์
        "prednisolone", "dexamethasone", "triamcinolone", "betamethasone", "hydrocortisone",
        "fluocinolone", "clobetasol", "budesonide",
        # กระเพาะ/ลำไส้
        "omeprazole", "esomeprazole", "pantoprazole", "lansoprazole", "ranitidine",
        "famotidine", "domperidone", "metoclopramide", "hyoscine", "loperamide",
        # เรื้อรัง/อื่น ๆ
        "metformin", "glipizide", "glibenclamide", "amlodipine", "enalapril", "losartan",
        "atenolol", "propranolol", "simvastatin", "atorvastatin", "allopurinol", "colchicine",
        "amitriptyline", "betahistine", "salbutamol", "theophylline", "albendazole",
        "mebendazole", "ketoconazole", "clotrimazole", "fluconazole", "acyclovir",
        "silver sulfadiazine", "sulfadiazine", "simethicone", "bromhexine", "ambroxol",
        "dextromethorphan", "carbocisteine", "acetylcysteine",
    ]),
]

LATIN = re.compile(r"[a-z]")


def _matches(term: str, text: str) -> bool:
    """คำอังกฤษจับทั้งคำ ("sulfa" ไม่ไปโดน "sulfate") คำไทยจับในข้อความได้เลย"""
    if LATIN.search(term):
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None
    return term in text


def suggest_category(*names: str) -> tuple[str, str] | None:
    """คืน (ประเภทที่เสนอ, คำที่ทำให้เสนอ) หรือ None ถ้าชื่อไม่บอกอะไรเลย"""
    text = " ".join(name or "" for name in names).lower()
    if not text.strip():
        return None
    for category, terms in HINTS:
        for term in terms:
            if _matches(term, text):
                return category, term
    return None
