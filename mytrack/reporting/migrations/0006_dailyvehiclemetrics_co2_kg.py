from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reporting', '0005_dailyfleethealthscore'),
    ]

    operations = [
        migrations.AddField(
            model_name='dailyvehiclemetrics',
            name='co2_kg',
            field=models.FloatField(default=0.0, help_text='Estimated CO₂ emitted (kg)'),
        ),
    ]
