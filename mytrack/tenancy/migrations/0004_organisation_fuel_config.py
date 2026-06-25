from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0003_organisation_speed_limit"),
    ]

    operations = [
        migrations.AddField(
            model_name="organisation",
            name="fuel_price_zar",
            field=models.DecimalField(
                decimal_places=2,
                default="22.00",
                help_text="Fuel price per litre (ZAR).",
                max_digits=6,
            ),
        ),
        migrations.AddField(
            model_name="organisation",
            name="idle_burn_rate_lph",
            field=models.DecimalField(
                decimal_places=2,
                default="3.50",
                help_text="Fuel burn rate while idling (litres per hour).",
                max_digits=5,
            ),
        ),
    ]
