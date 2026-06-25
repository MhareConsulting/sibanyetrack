from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("video_telematics", "0003_rename_video_telem_clipreq_org_idx_video_telem_organis_1cebcb_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="videochannel",
            name="stream_url",
            field=models.URLField(
                blank=True,
                max_length=2048,
                help_text="Live stream URL (MJPEG, HLS, etc.) served to the browser.",
            ),
        ),
    ]
