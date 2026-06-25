from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracking", "0013_alert_resolved_by_note"),
    ]

    operations = [
        migrations.AddField(
            model_name="trackedtrip",
            name="classification",
            field=models.CharField(
                choices=[("personal", "Personal"), ("business", "Business")],
                db_index=True,
                default="business",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="trackedtrip",
            name="start_label",
            field=models.CharField(blank=True, default="", max_length=300),
        ),
        migrations.AddField(
            model_name="trackedtrip",
            name="end_label",
            field=models.CharField(blank=True, default="", max_length=300),
        ),
    ]
