from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('vehicles', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='InspectionLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('driver_name', models.CharField(blank=True, max_length=200)),
                ('inspection_type', models.CharField(choices=[('pre_trip', 'Pre-Trip'), ('post_trip', 'Post-Trip')], max_length=10)),
                ('result', models.CharField(choices=[('pass', 'Pass'), ('defect', 'Defect Noted'), ('fail', 'Fail')], max_length=10)),
                ('checklist', models.JSONField(default=dict)),
                ('defects', models.TextField(blank=True)),
                ('odometer_km', models.FloatField(blank=True, null=True)),
                ('notes', models.TextField(blank=True)),
                ('submitted_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('vehicle', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='inspections', to='vehicles.vehicle')),
            ],
            options={
                'ordering': ['-submitted_at'],
            },
        ),
        migrations.AddIndex(
            model_name='inspectionlog',
            index=models.Index(fields=['vehicle', 'submitted_at'], name='mytrack_com_vehicle_idx'),
        ),
    ]
