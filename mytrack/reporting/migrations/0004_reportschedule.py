import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reporting', '0003_savedreporttemplate'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReportSchedule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('frequency', models.CharField(choices=[('daily', 'Daily'), ('weekly', 'Weekly'), ('monthly', 'Monthly')], max_length=10)),
                ('recipients', models.TextField(help_text='Comma-separated email addresses')),
                ('is_active', models.BooleanField(default=True)),
                ('last_run_at', models.DateTimeField(blank=True, null=True)),
                ('next_run_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('organisation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='report_schedules', to='tenancy.organisation')),
                ('template', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='schedules', to='reporting.savedreporttemplate')),
            ],
            options={
                'ordering': ['template__name'],
            },
        ),
    ]
