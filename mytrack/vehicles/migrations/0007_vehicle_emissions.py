from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0006_vehicle_expected_fuel_lper100km'),
    ]

    operations = [
        migrations.AddField(
            model_name='vehicle',
            name='fuel_type',
            field=models.CharField(
                choices=[('petrol', 'Petrol'), ('diesel', 'Diesel'), ('electric', 'Electric'), ('hybrid', 'Hybrid')],
                default='diesel',
                help_text='Fuel type — used for CO₂ calculations',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='vehicle',
            name='co2_per_litre',
            field=models.DecimalField(
                decimal_places=3,
                default='2.640',
                help_text='kg CO₂ per litre (Diesel: 2.640, Petrol 95: 2.310)',
                max_digits=6,
            ),
        ),
    ]
