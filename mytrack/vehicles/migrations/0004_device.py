from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0004_organisation_fuel_config"),
        ("vehicles", "0003_vehicle_fuel_tank_capacity"),
    ]

    operations = [
        migrations.CreateModel(
            name="Device",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("imei", models.CharField(max_length=30, unique=True)),
                ("model_name", models.CharField(blank=True, help_text="e.g. Teltonika FM3622", max_length=60)),
                ("phone_number", models.CharField(blank=True, max_length=20)),
                ("last_activity", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "organisation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="devices",
                        to="tenancy.organisation",
                    ),
                ),
                (
                    "vehicle",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="device",
                        to="vehicles.vehicle",
                    ),
                ),
            ],
            options={"ordering": ["-last_activity"]},
        ),
    ]
