from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fuel', '0004_fuelprichistory'),
    ]

    operations = [
        migrations.AddField(
            model_name='tankcalibration',
            name='poly_coefficients',
            field=models.JSONField(
                blank=True,
                null=True,
                help_text='Degree-N polynomial coefficients (highest power first) fitted from the strapping table',
            ),
        ),
        migrations.AddField(
            model_name='tankcalibration',
            name='poly_max_n',
            field=models.FloatField(
                blank=True,
                null=True,
                help_text='Maximum raw sensor value used during polynomial fitting (for clamping)',
            ),
        ),
    ]
