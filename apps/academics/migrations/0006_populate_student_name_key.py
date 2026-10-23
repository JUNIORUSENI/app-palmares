from django.db import migrations

from apps.core.text import name_key

BATCH = 1000


def populate_name_key(apps, schema_editor):
    """Calcule la clé de comparaison des élèves déjà présents en base."""
    Student = apps.get_model('academics', 'Student')
    batch = []
    for student in Student.objects.only('pk', 'full_name', 'name_key').iterator(chunk_size=2000):
        key = name_key(student.full_name)
        if key != student.name_key:
            student.name_key = key
            batch.append(student)
        if len(batch) >= BATCH:
            Student.objects.bulk_update(batch, ['name_key'])
            batch = []
    if batch:
        Student.objects.bulk_update(batch, ['name_key'])


class Migration(migrations.Migration):

    dependencies = [
        ('academics', '0005_student_name_key_and_indexes'),
    ]

    operations = [
        migrations.RunPython(populate_name_key, migrations.RunPython.noop),
    ]
