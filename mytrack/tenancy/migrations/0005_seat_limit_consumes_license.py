from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0004_organisation_fuel_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="organisation",
            name="seat_limit",
            field=models.PositiveSmallIntegerField(default=10, help_text="Maximum licensed users."),
        ),
        migrations.AddField(
            model_name="user",
            name="consumes_license",
            field=models.BooleanField(default=True, help_text="Counts toward the organisation's seat limit."),
        ),
    ]
