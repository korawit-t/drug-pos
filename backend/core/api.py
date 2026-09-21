from decimal import Decimal

from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError

from accounts.models import User
from inventory.models import PriceLevel

from .models import ShopSettings
from .promptpay import generate_payload

router = Router(tags=["meta"])


@router.get("/meta")
def meta(request):
    shop = ShopSettings.load()
    pharmacists = User.objects.filter(role=User.Role.PHARMACIST, is_active=True).order_by("id")
    return {
        "shop": {"name": shop.name, "phone": shop.phone},
        "today": timezone.localdate(),
        "near_expiry_days": shop.near_expiry_days,
        "promptpay_enabled": bool(shop.promptpay_id),
        "price_levels": [{"level": p.level, "name": p.name} for p in PriceLevel.objects.all()],
        "pharmacists": [{"id": u.pk, "name": u.label_name, "has_pin": bool(u.pin_hash)} for u in pharmacists],
    }


@router.get("/promptpay")
def promptpay(request, amount: Decimal):
    shop = ShopSettings.load()
    if not shop.promptpay_id:
        raise HttpError(404, "ยังไม่ได้ตั้งค่าพร้อมเพย์ของร้าน")
    if amount <= 0:
        raise HttpError(400, "ยอดเงินไม่ถูกต้อง")
    digits = "".join(ch for ch in shop.promptpay_id if ch.isdigit())
    return {"payload": generate_payload(shop.promptpay_id, amount), "account": "x" * (len(digits) - 4) + digits[-4:]}
