import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fuel', '0003_tank_calibration_and_raw_sensor_value'),
        ('tenancy', '0012_auditevent'),
    ]

    operations = [
        migrations.CreateModel(
            name='FuelPriceHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('effective_from', models.DateField(db_index=True)),
                ('petrol_95_zar', models.DecimalField(blank=True, decimal_places=3, max_digits=6, null=True)),
                ('petrol_93_zar', models.DecimalField(blank=True, decimal_places=3, max_digits=6, null=True)),
                ('diesel_500ppm_zar', models.DecimalField(blank=True, decimal_places=3, max_digits=6, null=True)),
                ('diesel_50ppm_zar', models.DecimalField(blank=True, decimal_places=3, max_digits=6, null=True)),
                ('source', models.CharField(default='manual', max_length=60)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('organisation', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='fuel_price_history',
                    to='tenancy.organisation',
                )),
            ],
            options={
                'ordering': ['-effective_from'],
                'unique_together': {('organisation', 'effective_from')},
            },
        ),
    ]
