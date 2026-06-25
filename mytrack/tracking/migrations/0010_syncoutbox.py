from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracking", "0009_roadspeedcache_gpsping_road_speed_limit_kmh_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="SyncOutbox",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("destination", models.CharField(db_index=True, max_length=32)),
                ("payload", models.JSONField()),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("last_attempted_at", models.DateTimeField(blank=True, null=True)),
                ("succeeded_at", models.DateTimeField(blank=True, null=True)),
                ("error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.AddIndex(
            model_name="syncoutbox",
            index=models.Index(
                fields=["destination", "succeeded_at", "attempts"],
                name="tracking_syncoutbox_dest_idx",
            ),
        ),
    ]
