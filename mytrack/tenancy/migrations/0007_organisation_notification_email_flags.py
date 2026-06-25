from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0006_organisation_fuel_thresholds"),
    ]

    operations = [
        migrations.AddField(
            model_name="organisation",
            name="email_daily_digest_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Send daily unresolved-alert digest (scheduled job).",
            ),
        ),
        migrations.AddField(
            model_name="organisation",
            name="email_weekly_summary_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Send weekly fleet and safety summary (scheduled job).",
            ),
        ),
        migrations.AddField(
            model_name="organisation",
            name="email_monthly_summary_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Send monthly fleet and safety summary (scheduled job).",
            ),
        ),
        migrations.AddField(
            model_name="organisation",
            name="email_expiry_warnings_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Send licence/PDP/document expiry warning emails (scheduled job).",
            ),
        ),
        migrations.AddField(
            model_name="organisation",
            name="notification_cc_emails",
            field=models.TextField(
                blank=True,
                help_text="Optional comma-separated addresses copied on scheduled org notification emails.",
            ),
        ),
    ]
