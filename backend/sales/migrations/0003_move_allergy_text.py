import re

from django.db import migrations


def split_text(apps, schema_editor):
    """Each comma/line-separated entry of the old free-text field becomes one allergy record."""
    Customer = apps.get_model("sales", "Customer")
    CustomerAllergy = apps.get_model("sales", "CustomerAllergy")
    for customer in Customer.objects.exclude(allergies=""):
        for entry in re.split(r"[,;\n]+", customer.allergies):
            if entry.strip():
                CustomerAllergy.objects.create(customer=customer, substance=entry.strip()[:200])


def join_text(apps, schema_editor):
    Customer = apps.get_model("sales", "Customer")
    for customer in Customer.objects.all():
        entries = [a.substance for a in customer.allergy_records.order_by("id") if a.substance]
        customer.allergies = ", ".join(entries)
        customer.save(update_fields=["allergies"])


class Migration(migrations.Migration):
    dependencies = [("sales", "0002_customer_allergies")]

    operations = [migrations.RunPython(split_text, join_text)]
