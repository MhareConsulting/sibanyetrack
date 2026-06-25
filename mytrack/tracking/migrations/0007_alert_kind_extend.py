from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracking', '0006_deliveryshare_stop_number'),
    ]

    operations = [
        migrations.AlterField(
            model_name='alert',
            name='kind',
            field=models.CharField(
                choices=[
                    ('speeding', 'Speeding'),
                    ('idle', 'Idle'),
                    ('fuel_theft', 'Fuel Theft'),
                    ('harsh_braking', 'Harsh Braking'),
                    ('harsh_accel', 'Harsh Acceleration'),
                    ('lane_departure', 'Lane Departure'),
                    ('fatigue', 'Driver Fatigue'),
                    ('phone_use', 'Phone Use'),
                    ('seatbelt', 'Seatbelt Violation'),
                    ('camera_event', 'Camera Event'),
                ],
                db_index=True,
                max_length=20,
            ),
        ),
    ]
