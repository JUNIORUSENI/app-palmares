from django.db import migrations

from apps.core.text import name_key, normalize_label, normalize_year_label

BATCH = 1000


def uppercase_names(apps, schema_editor):
    """Uniformise la casse des noms existants (convention : MAJUSCULES, espaces nettoyés).

    Les élèves n'ont aucune contrainte d'unicité : tous sont mis à jour. Les classes et les années, elles, sont
    uniques : celles dont la forme normalisée existe déjà sont laissées telles quelles (ce sont de vrais doublons,
    à réunir avec « manage.py merge_duplicates »).
    """
    Student = apps.get_model('academics', 'Student')
    batch = []
    for student in Student.objects.iterator(chunk_size=2000):
        new_name = normalize_label(student.full_name)
        if new_name != student.full_name:
            student.full_name = new_name
            student.name_key = name_key(new_name)
            batch.append(student)
        if len(batch) >= BATCH:
            Student.objects.bulk_update(batch, ['full_name', 'name_key'])
            batch = []
    if batch:
        Student.objects.bulk_update(batch, ['full_name', 'name_key'])

    ClassRoom = apps.get_model('academics', 'ClassRoom')
    classes = list(ClassRoom.objects.order_by('pk'))
    taken = {(c.name, c.section) for c in classes}
    for classroom in classes:
        current = (classroom.name, classroom.section)
        wanted = (normalize_label(classroom.name), normalize_label(classroom.section))
        if wanted == current or wanted in taken:
            continue
        taken.discard(current)
        taken.add(wanted)
        classroom.name, classroom.section = wanted
        classroom.save(update_fields=['name', 'section'])

    AcademicYear = apps.get_model('academics', 'AcademicYear')
    years = list(AcademicYear.objects.order_by('pk'))
    taken_labels = {y.label for y in years}
    for year in years:
        wanted = normalize_year_label(year.label)
        if wanted == year.label or wanted in taken_labels:
            continue
        taken_labels.discard(year.label)
        taken_labels.add(wanted)
        year.label = wanted
        year.save(update_fields=['label'])


class Migration(migrations.Migration):

    dependencies = [
        ('academics', '0006_populate_student_name_key'),
    ]

    operations = [
        migrations.RunPython(uppercase_names, migrations.RunPython.noop),
    ]
