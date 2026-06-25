from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('geofences', '0003_geofenceevent_geofences_g_vehicle_584675_idx'),
    ]

    operations = [
        migrations.AddField(
            model_name='geofence',
            name='enforce_hours',
            field=models.BooleanField(default=False, help_text='Only alert on entry outside the defined hours / days.'),
        ),
        migrations.AddField(
            model_name='geofence',
            name='hours_start',
            field=models.TimeField(blank=True, help_text='Authorised entry start (local time)', null=True),
        ),
        migrations.AddField(
            model_name='geofence',
            name='hours_end',
            field=models.TimeField(blank=True, help_text='Authorised entry end (local time)', null=True),
        ),
        migrations.AddField(
            model_name='geofence',
            name='active_days',
            field=models.CharField(default='0,1,2,3,4', help_text='CSV of weekday integers (Mon=0) when entry is authorised.', max_length=13),
        ),
    ]
