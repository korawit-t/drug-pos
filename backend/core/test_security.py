from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from accounts.models import User

from .security import security_warnings


def pharmacist(password="pharm1234", pin="1234") -> User:
    user = User(username="pharm1", role=User.Role.PHARMACIST, display_name="ภก.ทดสอบ")
    user.set_password(password)
    user.set_pin(pin)
    user.save()
    return user


class SecurityWarningTests(TestCase):
    def test_demo_password_and_guessable_pin_are_reported(self):
        User.objects.create_user("admin", password="admin1234", is_staff=True)
        pharmacist()
        warnings = " · ".join(security_warnings())
        self.assertIn("admin", warnings)
        self.assertIn("PIN ของ ภก.ทดสอบ", warnings)

    def test_nothing_to_report_once_they_are_changed(self):
        User.objects.create_user("admin", password="รหัสของร้านนี้-2569", is_staff=True)
        pharmacist(password="อีกรหัสของร้าน-2569", pin="284917")
        self.assertEqual(security_warnings(), [])

    @override_settings(DEBUG=True)
    def test_development_mode_is_reported(self):
        self.assertIn("DRUGPOS_DEBUG", security_warnings()[0])

    def test_command_fails_while_something_needs_fixing(self):
        user = User.objects.create_user("staff", password="staff1234")
        with self.assertRaises(SystemExit):
            call_command("check_security", stdout=StringIO())
        user.set_password("รหัสพนักงานของร้าน-2569")
        user.save()
        call_command("check_security", stdout=StringIO())  # passes once it's changed


class SeedDemoGuardTests(TestCase):
    def test_refused_on_a_shop_machine(self):
        # Tests run with DEBUG off, like a shop's server.
        with self.assertRaises(CommandError) as ctx:
            call_command("seed_demo", stdout=StringIO())
        self.assertIn("DRUGPOS_DEBUG=0", str(ctx.exception))
        self.assertFalse(User.objects.exists())

    @override_settings(DEBUG=True)
    def test_allowed_while_developing(self):
        call_command("seed_demo", stdout=StringIO())
        self.assertTrue(User.objects.filter(username="pharm1").exists())
