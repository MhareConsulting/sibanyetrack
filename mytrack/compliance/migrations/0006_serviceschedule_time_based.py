from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mytrack_compliance', '0005_add_warning_days_to_vehicledocument'),
    ]

    operations = [
        migrations.AddField(
            model_name='serviceschedule',
            name='interval_days',
            field=models.PositiveIntegerField(blank=True, help_text='Days between services (optional)', null=True),
        ),
        migrations.AddField(
            model_name='serviceschedule',
            name='last_serviced_at',
            field=models.DateField(blank=True, help_text='Date of most recent service', null=True),
        ),
    ]
