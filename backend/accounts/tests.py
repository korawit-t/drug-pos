from django.test import TestCase, override_settings
from django.utils import timezone

from .models import PinAttempt, User
from .services import PinError, verify_pin


def make_pharmacist(username="pharm", pin="1234") -> User:
    user = User(username=username, role=User.Role.PHARMACIST, display_name=f"ภก.{username}")
    user.set_password("x")
    user.set_pin(pin)
    user.save()
    return user


class VerifyPinTests(TestCase):
    def setUp(self):
        self.pharmacist = make_pharmacist()

    def verify(self, pin, pharmacist=None):
        return verify_pin(
            pharmacist_id=(pharmacist or self.pharmacist).pk, pin=pin, action=PinAttempt.Action.DISPENSE
        )

    def test_correct_pin_returns_pharmacist_and_logs(self):
        self.assertEqual(self.verify("1234"), self.pharmacist)
        self.assertTrue(PinAttempt.objects.get().success)

    def test_wrong_pin_is_logged_and_counted(self):
        with self.assertRaises(PinError):
            self.verify("0000")
        self.pharmacist.refresh_from_db()
        self.assertEqual(self.pharmacist.pin_failed_count, 1)
        self.assertFalse(PinAttempt.objects.get().success)

    @override_settings(PIN_MAX_ATTEMPTS=3, PIN_LOCK_MINUTES=5)
    def test_locks_after_too_many_wrong_pins(self):
        for _ in range(3):
            with self.assertRaises(PinError):
                self.verify("0000")
        self.pharmacist.refresh_from_db()
        self.assertGreater(self.pharmacist.pin_locked_until, timezone.now())
        # Even the right PIN is refused while locked.
        with self.assertRaises(PinError) as ctx:
            self.verify("1234")
        self.assertEqual(ctx.exception.status, 423)

    def test_success_resets_failure_count(self):
        with self.assertRaises(PinError):
            self.verify("0000")
        self.verify("1234")
        self.pharmacist.refresh_from_db()
        self.assertEqual(self.pharmacist.pin_failed_count, 0)

    def test_staff_cannot_approve(self):
        staff = User.objects.create_user("staff", password="x")
        staff.set_pin("1234")
        staff.save()
        with self.assertRaises(PinError):
            self.verify("1234", pharmacist=staff)
