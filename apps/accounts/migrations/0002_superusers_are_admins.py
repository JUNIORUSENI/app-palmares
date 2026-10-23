from django.db import migrations


def promote_superusers(apps, schema_editor):
    """Les superusers créés avec createsuperuser avaient le rôle « Lecteur » par défaut."""
    User = apps.get_model('accounts', 'User')
    User.objects.filter(is_superuser=True).exclude(role='admin').update(role='admin')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(promote_superusers, migrations.RunPython.noop),
    ]
