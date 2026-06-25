from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0005_seat_limit_consumes_license"),
    ]

    operations = [
        migrations.AddField(
            model_name="organisation",
            name="fuel_refuel_threshold_litres",
            field=models.FloatField(
                default=8.0,
                help_text="Fuel rise (L) required to classify as a refuel.",
            ),
        ),
        migrations.AddField(
            model_name="organisation",
            name="fuel_theft_threshold_litres",
            field=models.FloatField(
                default=5.0,
                help_text="Fuel drop (L) required to trigger theft/drain detection.",
            ),
        ),
        migrations.AddField(
            model_name="organisation",
            name="fuel_theft_speed_max_kmh",
            field=models.FloatField(
                default=5.0,
                help_text="Speed (km/h) at or below which a drop is classified as theft rather than drain.",
            ),
        ),
    ]
