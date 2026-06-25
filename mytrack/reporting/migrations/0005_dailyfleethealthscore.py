import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reporting', '0004_reportschedule'),
        ('tenancy', '0012_auditevent'),
    ]

    operations = [
        migrations.CreateModel(
            name='DailyFleetHealthScore',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('score_date', models.DateField(db_index=True)),
                ('score', models.FloatField()),
                ('driver_component', models.FloatField()),
                ('alert_component', models.FloatField()),
                ('compliance_component', models.FloatField()),
                ('utilisation_component', models.FloatField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('depot', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='fleet_health_scores',
                    to='tenancy.depot',
                )),
                ('organisation', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='fleet_health_scores',
                    to='tenancy.organisation',
                )),
            ],
            options={
                'ordering': ['-score_date'],
                'unique_together': {('organisation', 'depot', 'score_date')},
            },
        ),
    ]
