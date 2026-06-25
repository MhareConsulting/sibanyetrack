from django.db import migrations


def promote_username_admin_role(apps, schema_editor):
    User = apps.get_model("tenancy", "User")
    User.objects.filter(username__iexact="admin").update(role="admin")
    User.objects.filter(is_superuser=True).update(role="admin")


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0007_organisation_notification_email_flags"),
    ]

    operations = [
        migrations.RunPython(promote_username_admin_role, noop_reverse),
    ]
