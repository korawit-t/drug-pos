from django.db import migrations

DEFAULT_NAMES = {1: "ราคาปลีก", 2: "ราคาระดับ 2", 3: "ราคาระดับ 3", 4: "ราคาระดับ 4", 5: "ราคาระดับ 5"}


def create_levels(apps, schema_editor):
    PriceLevel = apps.get_model("inventory", "PriceLevel")
    for level, name in DEFAULT_NAMES.items():
        PriceLevel.objects.get_or_create(level=level, defaults={"name": name})


class Migration(migrations.Migration):
    dependencies = [("inventory", "0001_initial")]

    operations = [migrations.RunPython(create_levels, migrations.RunPython.noop)]
