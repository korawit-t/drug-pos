from django.db import migrations

NOTE = "ค่าเริ่มต้นของระบบ — เภสัชกรควรตรวจทานและแก้ไขให้เหมาะกับร้าน"

# Common drug classes behind allergy alerts. Keywords are matched as whole
# words in English (so "sulfa" doesn't hit "sulfate") and as substrings in Thai.
GROUPS = {
    "Penicillins (กลุ่มเพนิซิลลิน)": (
        "penicillin, penicillins, phenoxymethylpenicillin, amoxicillin, ampicillin, cloxacillin, "
        "dicloxacillin, flucloxacillin, piperacillin, เพนิซิลลิน, เพนนิซิลลิน, อะม็อกซีซิลลิน, อะมอกซีซิลลิน"
    ),
    "Cephalosporins (กลุ่มเซฟาโลสปอริน)": (
        "cephalosporin, cephalosporins, cephalexin, cefalexin, cefadroxil, cefaclor, cefuroxime, cefixime, "
        "cefdinir, cefpodoxime, cefazolin, ceftriaxone, เซฟาโลสปอริน, เซฟาเลกซิน"
    ),
    "Sulfonamides (ยาซัลฟา)": (
        "sulfa, sulfonamide, sulfonamides, sulphonamide, sulfamethoxazole, co-trimoxazole, cotrimoxazole, "
        "sulfadiazine, sulfasalazine, ซัลฟา"
    ),
    "NSAIDs (ยาแก้ปวดกลุ่มเอ็นเสด)": (
        "nsaid, nsaids, ibuprofen, diclofenac, naproxen, mefenamic, piroxicam, meloxicam, indomethacin, "
        "ketoprofen, etoricoxib, celecoxib, เอ็นเสด, ไอบูโพรเฟน, ไดโคลฟีแนค"
    ),
    "Aspirin / Salicylates (แอสไพริน)": "aspirin, acetylsalicylic, salicylate, salicylates, แอสไพริน",
    "Paracetamol (พาราเซตามอล)": "paracetamol, acetaminophen, พาราเซตามอล",
    "Macrolides (กลุ่มแมคโครไลด์)": "macrolide, macrolides, erythromycin, azithromycin, clarithromycin, roxithromycin",
    "Tetracyclines (กลุ่มเตตราไซคลิน)": "tetracycline, tetracyclines, doxycycline, minocycline",
    "Fluoroquinolones (กลุ่มฟลูออโรควิโนโลน)": (
        "fluoroquinolone, fluoroquinolones, quinolone, quinolones, ciprofloxacin, ofloxacin, levofloxacin, "
        "norfloxacin, moxifloxacin"
    ),
    "Allopurinol (อัลโลพูรินอล)": "allopurinol, อัลโลพูรินอล",
    "Carbamazepine (คาร์บามาซีปีน)": "carbamazepine, oxcarbazepine, คาร์บามาซีปีน",
    "Phenytoin (ฟีนิโทอิน)": "phenytoin, ฟีนิโทอิน",
    "Iodine (ไอโอดีน)": "iodine, povidone-iodine, betadine, ไอโอดีน, เบตาดีน",
}

# Pairs where an allergy to one may cross-react with the other — shown as a warning.
RELATED = [
    ("Penicillins (กลุ่มเพนิซิลลิน)", "Cephalosporins (กลุ่มเซฟาโลสปอริน)"),
    ("NSAIDs (ยาแก้ปวดกลุ่มเอ็นเสด)", "Aspirin / Salicylates (แอสไพริน)"),
    ("Carbamazepine (คาร์บามาซีปีน)", "Phenytoin (ฟีนิโทอิน)"),
]


def create_groups(apps, schema_editor):
    Allergen = apps.get_model("inventory", "Allergen")
    groups = {
        name: Allergen.objects.get_or_create(name=name, defaults={"keywords": keywords, "note": NOTE})[0]
        for name, keywords in GROUPS.items()
    }
    for a, b in RELATED:
        groups[a].related.add(groups[b])
        groups[b].related.add(groups[a])


class Migration(migrations.Migration):
    dependencies = [("inventory", "0005_allergens")]

    operations = [migrations.RunPython(create_groups, migrations.RunPython.noop)]
