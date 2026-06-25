from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("vehicles", "0005_vehiclestate_address"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicle",
            name="expected_fuel_lper100km",
            field=models.FloatField(
                blank=True,
                null=True,
                help_text="Expected fuel consumption (L/100 km). Used to flag excessive consumption.",
            ),
        ),
    ]
