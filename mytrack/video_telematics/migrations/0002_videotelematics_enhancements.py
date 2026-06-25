from django.db import migrations, models
import django.db.models.deletion


_TRIGGER_CHOICES = [
    ('harsh_event', 'Harsh event'),
    ('speeding', 'Speeding'),
    ('manual', 'Manual'),
    ('scheduled', 'Scheduled'),
    ('unknown', 'Unknown'),
    ('harsh_braking', 'Harsh braking'),
    ('harsh_accel', 'Harsh acceleration'),
    ('lane_departure', 'Lane departure'),
    ('fatigue', 'Driver fatigue'),
    ('phone_use', 'Phone use'),
    ('seatbelt', 'Seatbelt violation'),
]


class Migration(migrations.Migration):

    dependencies = [
        ('video_telematics', '0001_initial'),
        ('tracking', '0007_alert_kind_extend'),
        ('tenancy', '0005_seat_limit_consumes_license'),
        ('vehicles', '0005_vehiclestate_address'),
    ]

    operations = [
        # 1. Extend VideoTrigger choices on VideoAsset
        migrations.AlterField(
            model_name='videoasset',
            name='trigger_type',
            field=models.CharField(
                choices=_TRIGGER_CHOICES,
                default='unknown',
                max_length=20,
            ),
        ),
        # 2. Extend VideoTrigger choices on VideoUploadIntent
        migrations.AlterField(
            model_name='videouploadintent',
            name='trigger_type',
            field=models.CharField(
                choices=_TRIGGER_CHOICES,
                default='unknown',
                max_length=20,
            ),
        ),
        # 3. Add camera_last_seen to VideoChannel
        migrations.AddField(
            model_name='videochannel',
            name='camera_last_seen',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        # 4. Add is_active to VideoChannel
        migrations.AddField(
            model_name='videochannel',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
        # 5. Create ClipRequest model
        migrations.CreateModel(
            name='ClipRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Pending'),
                        ('fulfilled', 'Fulfilled'),
                        ('failed', 'Failed'),
                    ],
                    db_index=True,
                    default='pending',
                    max_length=12,
                )),
                ('vendor_request_id', models.CharField(blank=True, db_index=True, max_length=200)),
                ('requested_at', models.DateTimeField(auto_now_add=True)),
                ('fulfilled_at', models.DateTimeField(blank=True, null=True)),
                ('error_message', models.TextField(blank=True)),
                ('provider_payload', models.JSONField(blank=True, default=dict)),
                ('alert', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='clip_requests',
                    to='tracking.alert',
                )),
                ('channel', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='clip_requests',
                    to='video_telematics.videochannel',
                )),
                ('organisation', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='clip_requests',
                    to='tenancy.organisation',
                )),
                ('vehicle', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='clip_requests',
                    to='vehicles.vehicle',
                )),
                ('video_asset', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='clip_requests',
                    to='video_telematics.videoasset',
                )),
            ],
            options={
                'ordering': ['-requested_at'],
            },
        ),
        migrations.AddIndex(
            model_name='cliprequest',
            index=models.Index(fields=['organisation', 'requested_at'], name='video_telem_clipreq_org_idx'),
        ),
        migrations.AddIndex(
            model_name='cliprequest',
            index=models.Index(fields=['status', 'requested_at'], name='video_telem_clipreq_status_idx'),
        ),
    ]
