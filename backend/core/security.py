"""
Checks a shop can't easily do by eye: demo passwords left in place, a PIN
anyone would guess, or the server still running in development mode.

Run by `python manage.py check_security` and printed when the production
server starts.
"""

from django.conf import settings

# Accounts created by seed_demo, with the passwords printed in the README.
DEMO_PASSWORDS = {"admin": "admin1234", "staff": "staff1234", "pharm1": "pharm1234", "pharm2": "pharm1234"}
GUESSABLE_PINS = ["1234", "5678", "0000", "1111"]


def security_warnings() -> list[str]:
    from accounts.models import User

    warnings = []
    if settings.DEBUG:
        warnings.append(
            "ยังเปิดโหมดพัฒนาอยู่ (DRUGPOS_DEBUG=1) — เครื่องที่ใช้งานจริงต้องตั้ง DRUGPOS_DEBUG=0 "
            "ซึ่ง scripts\\windows\\start-server.bat ตั้งให้แล้ว"
        )
    for user in User.objects.filter(username__in=DEMO_PASSWORDS, is_active=True):
        if user.check_password(DEMO_PASSWORDS[user.username]):
            warnings.append(f"ผู้ใช้ {user.username} ยังใช้รหัสผ่านตัวอย่างที่เขียนไว้ใน README — เปลี่ยนก่อนใช้งานจริง")
    for pharmacist in User.objects.filter(role=User.Role.PHARMACIST, is_active=True).exclude(pin_hash=""):
        guessable = next((pin for pin in GUESSABLE_PINS if pharmacist.check_pin(pin)), None)
        if guessable:
            warnings.append(f"PIN ของ {pharmacist.label_name} เดาง่าย ({guessable}) — ตั้งใหม่ที่หลังร้าน")
    return warnings
