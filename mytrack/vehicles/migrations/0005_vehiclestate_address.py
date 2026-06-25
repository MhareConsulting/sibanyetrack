from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("vehicles", "0004_device"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehiclestate",
            name="last_address",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="vehiclestate",
            name="address_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
