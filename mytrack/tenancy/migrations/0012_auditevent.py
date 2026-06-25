import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0011_user_linked_driver_role_driver'),
    ]

    operations = [
        migrations.CreateModel(
            name='AuditEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(max_length=20)),
                ('target_model', models.CharField(max_length=60)),
                ('target_id', models.CharField(max_length=40)),
                ('target_repr', models.CharField(max_length=200)),
                ('delta', models.JSONField(default=dict)),
                ('occurred_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('organisation', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='audit_events', to='tenancy.organisation')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='audit_events', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-occurred_at'],
            },
        ),
    ]
