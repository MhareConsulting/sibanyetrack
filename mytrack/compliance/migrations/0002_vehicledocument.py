from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('mytrack_compliance', '0001_initial'),
        ('vehicles', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='VehicleDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(
                    choices=[
                        ('cof', 'Certificate of Fitness'),
                        ('licence_disc', 'Licence Disc'),
                        ('insurance', 'Insurance'),
                        ('roadworthy', 'Roadworthy Certificate'),
                        ('other', 'Other'),
                    ],
                    max_length=20,
                )),
                ('label', models.CharField(blank=True, max_length=100)),
                ('file', models.FileField(upload_to='vehicle_docs/%Y/%m/')),
                ('expiry_date', models.DateField(blank=True, null=True)),
                ('notes', models.TextField(blank=True)),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('vehicle', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='documents',
                    to='vehicles.vehicle',
                )),
            ],
            options={
                'ordering': ['-uploaded_at'],
            },
        ),
    ]
