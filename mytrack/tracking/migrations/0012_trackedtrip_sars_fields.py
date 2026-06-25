from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracking', '0011_add_alert_severity_and_geofence_after_hours'),
    ]

    operations = [
        migrations.AddField(
            model_name='trackedtrip',
            name='business_purpose',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='trackedtrip',
            name='destination_name',
            field=models.CharField(blank=True, max_length=200),
        ),
    ]
