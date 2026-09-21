from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import PinAttempt, User


class PinError(Exception):
    def __init__(self, message: str, status: int = 403):
        super().__init__(message)
        self.message = message
        self.status = status


def client_ip(request) -> str:
    return request.META.get("REMOTE_ADDR", "") if request else ""


def verify_pin(
    *, pharmacist_id: int, pin: str, action: str, requested_by=None, detail: str = "", terminal: str = ""
) -> User:
    """
    Check a pharmacist's PIN. Every attempt is logged; too many wrong PINs lock
    that pharmacist's PIN for a few minutes. Raises PinError on failure.

    Call this outside any surrounding transaction: the attempt log and the
    failure counter are committed here, before the error is raised, so a wrong
    PIN is recorded even though the caller's work doesn't happen.
    """
    with transaction.atomic():
        pharmacist = User.objects.filter(pk=pharmacist_id, is_active=True).first()
        if pharmacist is None or not pharmacist.is_pharmacist:
            raise PinError("ต้องเป็นเภสัชกรเท่านั้น")
        if not pharmacist.pin_hash:
            raise PinError(f"{pharmacist.label_name} ยังไม่ได้ตั้ง PIN (ตั้งได้ที่หลังร้าน)")

        now = timezone.now()
        if pharmacist.pin_locked_until and pharmacist.pin_locked_until > now:
            minutes = int((pharmacist.pin_locked_until - now).total_seconds() // 60) + 1
            raise PinError(f"PIN ของ {pharmacist.label_name} ถูกล็อก ลองใหม่ในอีก {minutes} นาที", status=423)

        ok = pharmacist.check_pin(pin)
        PinAttempt.objects.create(
            pharmacist=pharmacist,
            requested_by=requested_by if getattr(requested_by, "is_authenticated", False) else None,
            action=action,
            success=ok,
            detail=detail[:200],
            terminal=terminal[:64],
        )
        if ok:
            pharmacist.pin_failed_count = 0
            pharmacist.pin_locked_until = None
            pharmacist.save(update_fields=["pin_failed_count", "pin_locked_until"])
            return pharmacist

        pharmacist.pin_failed_count += 1
        if pharmacist.pin_failed_count >= settings.PIN_MAX_ATTEMPTS:
            pharmacist.pin_failed_count = 0
            pharmacist.pin_locked_until = now + timedelta(minutes=settings.PIN_LOCK_MINUTES)
            error = PinError(
                f"PIN ผิด {settings.PIN_MAX_ATTEMPTS} ครั้ง ล็อก {settings.PIN_LOCK_MINUTES} นาที", status=423
            )
        else:
            left = settings.PIN_MAX_ATTEMPTS - pharmacist.pin_failed_count
            error = PinError(f"PIN ไม่ถูกต้อง (เหลืออีก {left} ครั้ง)")
        pharmacist.save(update_fields=["pin_failed_count", "pin_locked_until"])
    raise error
