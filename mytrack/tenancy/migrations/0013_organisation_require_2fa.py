from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0012_auditevent'),
    ]

    operations = [
        migrations.AddField(
            model_name='organisation',
            name='require_2fa',
            field=models.BooleanField(
                default=False,
                help_text='Require all users in this organisation to use two-factor authentication (TOTP).',
            ),
        ),
    ]
