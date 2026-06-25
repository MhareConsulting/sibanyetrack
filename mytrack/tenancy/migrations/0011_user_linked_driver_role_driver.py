import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0010_organisation_notify_critical_instant'),
        ('drivers', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[
                    ('admin', 'Admin'),
                    ('dispatcher', 'Dispatcher'),
                    ('viewer', 'Viewer'),
                    ('driver', 'Driver'),
                ],
                default='dispatcher',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='linked_driver',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='user_accounts',
                to='drivers.driver',
            ),
        ),
    ]
