import importlib
from io import StringIO

import pytest
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse

from apps.academics.models import AcademicYear, ClassRoom, GradeRecord, Student
from apps.academics.services import MergeError, merge_classrooms, merge_students, merge_years
from apps.audit.models import AuditLog
from apps.imports.models import SourceFile

pytestmark = pytest.mark.django_db


# ── Tout est stocké en majuscules ────────────────────────────────

def test_student_names_are_always_stored_uppercase_and_tidy():
    student = Student.objects.create(full_name='  lukusa   kalombo Noé ')
    assert student.full_name == 'LUKUSA KALOMBO NOÉ'
    assert student.name_key == 'LUKUSA KALOMBO NOE'


def test_renaming_a_student_keeps_the_convention():
    student = Student.objects.create(full_name='A')
    student.full_name = 'kabila  joseph'
    student.save(update_fields=['full_name'])
    student.refresh_from_db()
    assert (student.full_name, student.name_key) == ('KABILA JOSEPH', 'KABILA JOSEPH')


def test_classroom_and_year_are_normalized_too():
    room = ClassRoom.objects.create(name='Classe de  Seconde', section='Secondaire')
    year = AcademicYear.objects.create(label='2024 - 2025')
    assert (room.name, room.section, year.label) == ('CLASSE DE SECONDE', 'SECONDAIRE', '2024-2025')


def test_forms_detect_a_duplicate_before_it_is_saved():
    """L'admin Django vérifie l'unicité avant save() : la valeur saisie doit déjà être normalisée."""
    ClassRoom.objects.create(name='CLASSE DE SECONDE', section='SECONDAIRE')
    duplicate = ClassRoom(name='Classe de seconde', section='Secondaire')
    with pytest.raises(ValidationError):
        duplicate.full_clean()
    AcademicYear.objects.create(label='2024-2025')
    with pytest.raises(ValidationError):
        AcademicYear(label='2024 - 2025').full_clean()


def test_inline_name_edit_stores_uppercase(make_grade, as_user, editor):
    make_grade('ANCIEN NOM', 50)
    student = Student.objects.get()
    response = as_user(editor).post(reverse('academics:student_name_edit', args=[student.pk]), {'full_name': 'nouveau   nom'})
    student.refresh_from_db()
    assert student.full_name == 'NOUVEAU NOM' and 'NOUVEAU NOM' in response.content.decode()


@pytest.mark.parametrize('typed', ['', '   ', 'X' * 201])
def test_inline_name_edit_rejects_empty_or_too_long_names(make_grade, as_user, editor, typed):
    make_grade('ANCIEN NOM', 50)
    student = Student.objects.get()
    response = as_user(editor).post(reverse('academics:student_name_edit', args=[student.pk]), {'full_name': typed})
    student.refresh_from_db()
    assert student.full_name == 'ANCIEN NOM' and response.status_code == 200      # pas d'erreur 500


# ── Recherche tolérante ──────────────────────────────────────────

def test_search_ignores_case_accents_and_spacing(make_grade, as_user, reader):
    make_grade('MULAJ KAPEND MOÏSE', 50)
    make_grade('AUTRE ELEVE', 50)
    client = as_user(reader)
    for typed in ('moise', 'MOÏSE', '  mulaj   kapend ', 'Moïse'):
        assert client.get(reverse('academics:student_list'), {'q': typed}).context['total_count'] == 1, typed
    csv_rows = client.get(reverse('exports:csv_students'), {'q': 'moise'}).content.decode('utf-8-sig').strip().splitlines()
    assert len(csv_rows) == 2


# ── Migration des données existantes ─────────────────────────────

def test_migration_uppercases_students_and_safe_names_but_leaves_collisions():
    migration = importlib.import_module('apps.academics.migrations.0007_uppercase_names')
    Student.objects.bulk_create([Student(full_name='Lukusa  Kalombo Noé'), Student(full_name='DEJA MAJUSCULE')])
    ClassRoom.objects.bulk_create([
        ClassRoom(name='7e  EB/A', section='Secondaire'),          # sans collision : renommée
        ClassRoom(name='7E EB/G', section='SECONDAIRE'),
        ClassRoom(name='7e  EB/G', section='Secondaire'),          # collision avec la ligne du dessus : laissée
    ])
    AcademicYear.objects.bulk_create([AcademicYear(label='2023 - 2024'), AcademicYear(label='2024-2025'), AcademicYear(label='2024 / 2025')])

    migration.uppercase_names(django_apps, None)

    assert sorted(Student.objects.values_list('full_name', flat=True)) == ['DEJA MAJUSCULE', 'LUKUSA KALOMBO NOÉ']
    assert Student.objects.get(full_name='LUKUSA KALOMBO NOÉ').name_key == 'LUKUSA KALOMBO NOE'
    assert sorted(ClassRoom.objects.values_list('name', 'section')) == [
        ('7E EB/A', 'SECONDAIRE'), ('7E EB/G', 'SECONDAIRE'), ('7e  EB/G', 'Secondaire'),
    ]
    assert sorted(AcademicYear.objects.values_list('label', flat=True)) == ['2023-2024', '2024 / 2025', '2024-2025']


# ── Fusion de classes et d'années ────────────────────────────────

def _bulk_class(name, section='SECONDAIRE'):
    ClassRoom.objects.bulk_create([ClassRoom(name=name, section=section)])
    return ClassRoom.objects.get(name=name)


def test_merge_classrooms_moves_results_and_resolves_conflicts(make_grade):
    make_grade('A', 70, classroom='7 EB G')
    make_grade('B', 55, classroom='7 EB G')
    twin = _bulk_class('7  EB G')
    student_a = Student.objects.get(full_name='A')
    student_c = Student.objects.create(full_name='C')
    year = AcademicYear.objects.get()
    GradeRecord.objects.create(student=student_a, classroom=twin, academic_year=year, percentage=10)   # conflit avec A
    GradeRecord.objects.create(student=student_c, classroom=twin, academic_year=year, percentage=60)   # à déplacer
    target = ClassRoom.objects.get(name='7 EB G')

    result = merge_classrooms(twin, target)

    assert result['moved'] == 1 and len(result['conflicts']) == 1
    assert not ClassRoom.objects.filter(pk=twin.pk).exists()
    assert target.grades.count() == 3
    assert target.grades.get(student=student_a).percentage == 70      # la note de la cible est gardée


def test_merge_years_moves_results_and_source_files(make_grade, editor):
    make_grade('A', 70, year='2024-2025')
    AcademicYear.objects.bulk_create([AcademicYear(label='2024 - 2025')])
    twin = AcademicYear.objects.get(label='2024 - 2025')
    GradeRecord.objects.create(student=Student.objects.create(full_name='B'), classroom=ClassRoom.objects.get(),
                               academic_year=twin, percentage=40)
    sf = SourceFile.objects.create(imported_by=editor, original_filename='f.xlsx', file='imports/f.xlsx', academic_year=twin)
    target = AcademicYear.objects.get(label='2024-2025')

    merge_years(twin, target)

    sf.refresh_from_db()
    assert sf.academic_year == target and target.grades.count() == 2
    assert AcademicYear.objects.count() == 1


def test_merging_something_with_itself_is_refused(make_grade):
    make_grade('A', 70)
    with pytest.raises(MergeError):
        merge_classrooms(ClassRoom.objects.get(), ClassRoom.objects.get())
    with pytest.raises(MergeError):
        merge_students(Student.objects.get(), Student.objects.get())


# ── Commande merge_duplicates ────────────────────────────────────

def run(*args):
    out = StringIO()
    call_command('merge_duplicates', *args, stdout=out)
    return out.getvalue()


@pytest.fixture
def messy_data(make_grade):
    make_grade('MULAJ KAPEND MOÏSE', 70, year='2023-2024')
    make_grade('MULAJ KAPEND MOÏSE', 75, year='2024-2025')
    make_grade('Mulaj Kapend Moise', 60, year='2022-2023')
    make_grade('Mulaj Kapend Moise', 99, year='2024-2025')            # même année : en conflit
    make_grade('AUTRE ELEVE', 50, classroom='CLASSE DE SECONDE')
    # Données « à l'ancienne » (créées sans passer par save()) : casse mixte, classe et année en double
    Student.objects.bulk_create([Student(full_name='Lukusa Kalombo Noe', name_key='LUKUSA KALOMBO NOE')])
    twin_class = _bulk_class('Classe de Seconde', 'Secondaire')
    AcademicYear.objects.bulk_create([AcademicYear(label='2024 - 2025')])
    GradeRecord.objects.create(student=Student.objects.get(full_name='Lukusa Kalombo Noe'), classroom=twin_class,
                               academic_year=AcademicYear.objects.get(label='2024 - 2025'), percentage=30)


def test_dry_run_changes_nothing_and_reports(messy_data):
    before = (Student.objects.count(), ClassRoom.objects.count(), AcademicYear.objects.count())
    output = run()
    assert 'SIMULATION' in output and 'ÉLÈVE' in output and 'CLASSE' in output and 'ANNÉE' in output
    assert (Student.objects.count(), ClassRoom.objects.count(), AcademicYear.objects.count()) == before
    assert Student.objects.filter(full_name='Lukusa Kalombo Noe').exists() and not AuditLog.objects.exists()


def test_apply_merges_everything_and_uniformizes_the_case(messy_data):
    run('--apply')

    assert sorted(Student.objects.values_list('full_name', flat=True)) == ['AUTRE ELEVE', 'LUKUSA KALOMBO NOE', 'MULAJ KAPEND MOÏSE']
    assert sorted(ClassRoom.objects.values_list('name', 'section')) == [('7 EB A', 'SECONDAIRE'), ('CLASSE DE SECONDE', 'SECONDAIRE')]
    assert sorted(AcademicYear.objects.values_list('label', flat=True)) == ['2022-2023', '2023-2024', '2024-2025']
    survivor = Student.objects.get(full_name='MULAJ KAPEND MOÏSE')
    assert survivor.grades.count() == 3
    assert survivor.grades.get(academic_year__label='2024-2025').percentage == 75         # la cible gagne le conflit
    models = set(AuditLog.objects.filter(action='merge').values_list('model_name', flat=True))
    assert models == {'Student', 'ClassRoom', 'AcademicYear'}
    assert AuditLog.objects.filter(action='merge', user__isnull=True).count() == AuditLog.objects.count()
    assert GradeRecord.objects.count() == 5       # 6 avant ; le seul doublon (2024-2025 de MOÏSE) est écarté


def test_second_run_finds_nothing(messy_data):
    run('--apply')
    assert 'Rien à faire' in run('--apply')


def test_distinct_names_are_never_merged(make_grade):
    make_grade('KABASELE MARIE', 50)
    make_grade('KABASELE MARIA', 60)
    assert 'Rien à faire' in run('--apply')
    assert Student.objects.count() == 2 and GradeRecord.objects.count() == 2


def test_missing_name_keys_are_recomputed_before_merging(make_grade):
    make_grade('MULAJ KAPEND MOÏSE', 70)
    make_grade('Mulaj Kapend Moise', 60, year='2023-2024')
    Student.objects.update(name_key='')           # comme après un retour en arrière puis un nouveau déploiement
    output = run('--apply')
    assert 'recalcul' in output and Student.objects.count() == 1
