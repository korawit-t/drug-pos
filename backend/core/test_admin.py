from io import StringIO
from types import SimpleNamespace

from django.contrib import admin
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from accounts.models import User


@override_settings(DEBUG=True)  # seed_demo refuses to run on a shop machine
class AdminSmokeTests(TestCase):
    """Every back-office page opens with the demo data loaded."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=StringIO())

    def setUp(self):
        self.admin_user = User.objects.get(username="admin")
        self.client.force_login(self.admin_user)
        self.request = RequestFactory().get("/")
        self.request.user = self.admin_user

    def test_changelists_add_and_change_pages_render(self):
        for model, model_admin in admin.site._registry.items():
            opts = model._meta
            prefix = f"admin:{opts.app_label}_{opts.model_name}"
            with self.subTest(model=opts.label):
                self.assertEqual(self.client.get(reverse(f"{prefix}_changelist")).status_code, 200)
                if model_admin.has_add_permission(self.request):
                    self.assertEqual(self.client.get(reverse(f"{prefix}_add")).status_code, 200)
                obj = model.objects.first()
                if obj is not None:
                    self.assertEqual(self.client.get(reverse(f"{prefix}_change", args=[obj.pk])).status_code, 200)

    def test_saving_a_user_with_new_pin_sets_it(self):
        pharmacist = User.objects.get(username="pharm1")
        user_admin = admin.site._registry[User]
        user_admin.save_model(self.request, pharmacist, SimpleNamespace(cleaned_data={"new_pin": "4321"}), True)
        pharmacist.refresh_from_db()
        self.assertTrue(pharmacist.check_pin("4321"))
