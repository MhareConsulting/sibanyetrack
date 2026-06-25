from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('tracking', '0004_alert_model'),
        ('vehicles', '0002_vehicle_home_depot_vehicledepotassignment'),
    ]

    operations = [
        migrations.CreateModel(
            name='FuelReading',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fuel_level_litres', models.FloatField()),
                ('speed_kmh', models.FloatField(blank=True, null=True)),
                ('lat', models.FloatField(blank=True, null=True)),
                ('lon', models.FloatField(blank=True, null=True)),
                ('driver_name', models.CharField(blank=True, max_length=200)),
                ('device_timestamp', models.DateTimeField(db_index=True)),
                ('received_at', models.DateTimeField(auto_now_add=True)),
                ('tracked_trip', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='fuel_readings',
                    to='tracking.trackedtrip',
                )),
                ('vehicle', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='fuel_readings',
                    to='vehicles.vehicle',
                )),
            ],
            options={'ordering': ['-device_timestamp']},
        ),
        migrations.AddIndex(
            model_name='fuelreading',
            index=models.Index(fields=['vehicle', 'device_timestamp'], name='fuel_reading_vehicle_ts_idx'),
        ),
        migrations.CreateModel(
            name='FuelEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(
                    choices=[('refuel', 'Refuel'), ('theft', 'Fuel Theft'), ('drain', 'Unexplained Drain')],
                    db_index=True, max_length=10,
                )),
                ('occurred_at', models.DateTimeField(db_index=True)),
                ('level_before', models.FloatField()),
                ('level_after', models.FloatField()),
                ('delta_litres', models.FloatField()),
                ('driver_name', models.CharField(blank=True, max_length=200)),
                ('lat', models.FloatField(blank=True, null=True)),
                ('lon', models.FloatField(blank=True, null=True)),
                ('acknowledged', models.BooleanField(default=False)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('vehicle', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='fuel_events',
                    to='vehicles.vehicle',
                )),
            ],
            options={'ordering': ['-occurred_at']},
        ),
        migrations.AddIndex(
            model_name='fuelevent',
            index=models.Index(fields=['vehicle', 'occurred_at'], name='fuel_event_vehicle_ts_idx'),
        ),
    ]
