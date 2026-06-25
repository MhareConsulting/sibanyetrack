import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reporting', '0002_add_warning_days_to_vehicledocument'),
        ('tenancy', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SavedReportTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120)),
                ('domain', models.CharField(choices=[('speed', 'Speed'), ('fuel', 'Fuel'), ('geofence', 'Geofence'), ('route', 'Route')], max_length=20)),
                ('config', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='saved_report_templates', to=settings.AUTH_USER_MODEL)),
                ('organisation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='saved_report_templates', to='tenancy.organisation')),
            ],
            options={
                'ordering': ['name'],
                'unique_together': {('organisation', 'name')},
            },
        ),
    ]
