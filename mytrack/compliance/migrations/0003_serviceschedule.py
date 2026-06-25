from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('mytrack_compliance', '0002_vehicledocument'),
        ('vehicles', '0003_vehicle_fuel_tank_capacity'),
    ]

    operations = [
        migrations.CreateModel(
            name='ServiceSchedule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, help_text='e.g. Oil Change, 15 000 km Service')),
                ('interval_km', models.PositiveIntegerField(help_text='Service repeat interval in km')),
                ('last_service_km', models.FloatField(blank=True, null=True, help_text='Odometer reading when last serviced')),
                ('last_service_date', models.DateField(blank=True, null=True)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('vehicle', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='service_schedules',
                    to='vehicles.vehicle',
                )),
            ],
            options={
                'ordering': ['vehicle__registration', 'name'],
            },
        ),
    ]
