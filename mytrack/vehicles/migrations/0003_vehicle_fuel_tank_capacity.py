from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0002_vehicle_home_depot_vehicledepotassignment'),
    ]

    operations = [
        migrations.AddField(
            model_name='vehicle',
            name='fuel_tank_capacity_litres',
            field=models.FloatField(
                blank=True, null=True,
                help_text='Full tank capacity — used to convert % probe readings to litres',
            ),
        ),
    ]
