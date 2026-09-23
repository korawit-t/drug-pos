"""
Drug allergy matching.

A customer's allergy record and a product are both turned into allergen
groups (Allergen) — from the explicit links and from the names:

  "Penicillin (ผื่นลมพิษ)"   → Penicillins
  "Amoxicillin trihydrate"  → Penicillins   → direct alert
  "Cephalexin"              → Cephalosporins, related to Penicillins → cross alert

A record whose text names the product itself ("Tramadol") also alerts even
when no group knows that drug.
"""

import re
from dataclasses import dataclass

from .models import Allergen

THAI = re.compile(r"[฀-๿]")


def matcher(term: str):
    """Whole-word match for Latin text ("sulfa" must not hit "sulfate"); substring for Thai, which has no spaces."""
    term = term.strip().lower()
    if not term:
        return None
    if THAI.search(term):
        return lambda text: term in text
    pattern = re.compile(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])")
    return lambda text: pattern.search(text) is not None


class AllergyIndex:
    """All allergen groups, loaded once per request."""

    def __init__(self):
        groups = list(Allergen.objects.prefetch_related("related"))
        self.names = {g.pk: g.name for g in groups}
        self.related = {g.pk: {r.pk for r in g.related.all()} for g in groups}
        self.matchers = {g.pk: [m for m in map(matcher, g.terms) if m] for g in groups}

    def groups_in(self, text: str) -> set[int]:
        text = (text or "").lower()
        return {pk for pk, matchers in self.matchers.items() if any(m(text) for m in matchers)}

    def product_groups(self, product) -> set[int]:
        explicit = {g.pk for g in product.allergens.all()}
        return explicit | self.groups_in(f"{product.trade_name} {product.generic_name}")

    def record_groups(self, record) -> set[int]:
        return ({record.allergen_id} if record.allergen_id else set()) | self.groups_in(record.substance)

    def describe(self, group_ids) -> str:
        return ", ".join(sorted(self.names[pk] for pk in group_ids))


@dataclass
class AllergyAlert:
    level: str  # "direct": same drug or same group · "cross": a group that may cross-react
    allergy_id: int
    allergy: str
    reaction: str
    severity: str
    severity_label: str
    message: str


def allergy_alerts(records, products, index: AllergyIndex | None = None) -> dict[int, list[AllergyAlert]]:
    """Alerts per product id for one customer's allergy records."""
    records = list(records)
    if not records:
        return {}
    index = index or AllergyIndex()
    alerts: dict[int, list[AllergyAlert]] = {}
    for product in products:
        groups = index.product_groups(product)
        names = f"{product.trade_name} {product.generic_name}".lower()
        found = []
        for record in records:
            record_groups = index.record_groups(record)
            same = groups & record_groups
            by_name = matcher(record.substance) if record.substance else None
            if same:
                level, message = "direct", f"{product.display_name} อยู่ในกลุ่ม {index.describe(same)} ที่ลูกค้าแพ้"
            elif by_name and by_name(names):
                level, message = "direct", f"{product.display_name} ตรงกับยาที่ลูกค้าแพ้ ({record.label})"
            else:
                cross = groups & set().union(*(index.related.get(pk, set()) for pk in record_groups))
                if not cross:
                    continue
                level = "cross"
                message = f"{product.display_name} อยู่ในกลุ่ม {index.describe(cross)} ซึ่งอาจแพ้ข้ามกับ {record.label}"
            found.append(
                AllergyAlert(
                    level=level,
                    allergy_id=record.pk,
                    allergy=record.label,
                    reaction=record.reaction,
                    severity=record.severity,
                    severity_label=record.get_severity_display(),
                    message=message,
                )
            )
        if found:
            alerts[product.pk] = found
    return alerts
