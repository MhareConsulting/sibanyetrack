from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0009_organisation_road_speed_limits_enabled_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='organisation',
            name='notify_critical_instant',
            field=models.BooleanField(default=True, help_text='Send an immediate email when a CRITICAL-severity alert is created (fuel theft, harsh events, fatigue, etc.).'),
        ),
    ]
