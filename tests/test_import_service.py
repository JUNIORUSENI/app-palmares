from decimal import Decimal

import pytest

from apps.academics.models import AcademicYear, ClassRoom, GradeRecord, Student
from apps.imports.models import ImportChange, SourceFile
from apps.imports.services import do_import, dry_run, rollback_import

pytestmark = pytest.mark.django_db

ROW = ('Jean Dupont', 75, '7 EB A', 'Secondaire', '2024-2025')


def run_import(editor, source_file, make_xlsx, rows, **kwargs):
    path = make_xlsx(rows, **kwargs)
    sf = source_file(editor, path)
    return sf, do_import(sf.file.path, sf)


# ── Création ─────────────────────────────────────────────────────

def test_import_creates_students_classes_years_and_grades(editor, source_file, make_xlsx):
    sf, result = run_import(editor, source_file, make_xlsx, [
        ROW, ('Marie Kasongo', '82,5', '7 EB A', 'Secondaire', '2024-2025'),
    ])
    assert result['created'] == 2 and result['imported'] == 2 and result['skipped'] == 0
    assert Student.objects.count() == 2
    grade = GradeRecord.objects.get(student__full_name='MARIE KASONGO')
    assert grade.percentage == Decimal('82.50')
    assert grade.source_file == sf
    sf.refresh_from_db()
    assert sf.academic_year.label == '2024-2025'


def test_blank_percentage_creates_an_ungraded_record(editor, source_file, make_xlsx):
    _, result = run_import(editor, source_file, make_xlsx, [('Jean Dupont', None, '7 EB A', 'Secondaire', '2024-2025')])
    assert result['created'] == 1
    assert GradeRecord.objects.get().percentage is None


def test_invalid_rows_are_skipped_but_valid_ones_imported(editor, source_file, make_xlsx):
    _, result = run_import(editor, source_file, make_xlsx, [
        ROW, ('', 50, '7 EB A', 'Secondaire', '2024-2025'), ('Paul Mbuyi', 250, '7 EB A', 'Secondaire', '2024-2025'),
    ])
    assert (result['created'], result['skipped']) == (1, 2)


def test_too_long_name_is_a_row_error_not_a_crash(editor, source_file, make_xlsx):
    _, result = run_import(editor, source_file, make_xlsx, [ROW, ('X' * 300, 50, '7 EB A', 'Secondaire', '2024-2025')])
    assert (result['created'], result['skipped']) == (1, 1)


def test_duplicate_rows_in_one_file_are_flagged_not_silently_overwritten(editor, source_file, make_xlsx):
    path = make_xlsx([ROW, ('JEAN  DUPONT', 99, '7 EB A', 'SECONDAIRE', '2024 - 2025')])
    report = dry_run(path)
    assert (report['valid_rows'], report['error_rows']) == (1, 1)
    assert any('doublon' in e for e in report['errors'])

    sf = source_file(editor, path)
    assert do_import(sf.file.path, sf)['created'] == 1
    assert GradeRecord.objects.get().percentage == Decimal('75.00')   # la 1re ligne est conservée


# ── Pas de doublons à cause de la graphie ────────────────────────

def test_name_spelling_variants_reuse_the_same_student(editor, source_file, make_xlsx):
    existing = Student.objects.create(full_name="N'DAYE-MUKENDI JEAN")
    _, result = run_import(editor, source_file, make_xlsx, [("n’daye mukendi  jean", 70, '7 EB A', 'Secondaire', '2024-2025')])
    assert Student.objects.count() == 1
    assert GradeRecord.objects.get().student == existing
    assert result['created'] == 1


def test_year_spelling_variants_reuse_the_same_year(editor, source_file, make_xlsx):
    AcademicYear.objects.create(label='2024-2025')
    run_import(editor, source_file, make_xlsx, [('Jean Dupont', 70, '7 EB A', 'Secondaire', '2024 - 2025')])
    assert AcademicYear.objects.count() == 1


def test_same_class_name_in_another_section_is_a_different_class(editor, source_file, make_xlsx):
    primary = ClassRoom.objects.create(name='1ERE A', section='PRIMAIRE')
    run_import(editor, source_file, make_xlsx, [('Jean Dupont', 70, '1ERE A', 'Secondaire', '2024-2025')])
    grade = GradeRecord.objects.get()
    assert grade.classroom != primary
    assert grade.classroom.section == 'SECONDAIRE'
    assert ClassRoom.objects.count() == 2


def test_existing_student_is_matched_by_key_even_if_stored_untidy(editor, source_file, make_xlsx):
    Student.objects.create(full_name='Ndayé   Mukendi')
    run_import(editor, source_file, make_xlsx, [('NDAYE MUKENDI', 70, '7 EB A', 'Secondaire', '2024-2025')])
    assert Student.objects.count() == 1


# ── Notes déjà présentes ─────────────────────────────────────────

def test_existing_grade_is_updated_and_the_change_recorded(editor, source_file, make_xlsx, make_grade):
    grade = make_grade('JEAN DUPONT', 60)
    sf, result = run_import(editor, source_file, make_xlsx, [ROW])
    grade.refresh_from_db()
    assert (result['created'], result['updated']) == (0, 1)
    assert grade.percentage == Decimal('75.00')
    assert grade.source_file is None                      # la note n'appartient pas à ce fichier
    change = ImportChange.objects.get()
    assert (change.grade, change.old_percentage, change.new_percentage) == (grade, Decimal('60.00'), Decimal('75.00'))


def test_verified_grade_is_never_overwritten(editor, source_file, make_xlsx, make_grade):
    grade = make_grade('JEAN DUPONT', 60, is_verified=True, verified_by=editor)
    _, result = run_import(editor, source_file, make_xlsx, [ROW])
    grade.refresh_from_db()
    assert grade.percentage == Decimal('60.00') and grade.is_verified
    assert result['blocked'] == 1 and result['updated'] == 0
    assert 'vérifié' in result['blocked_details'][0]
    assert not ImportChange.objects.exists()


def test_empty_cell_does_not_erase_an_existing_grade(editor, source_file, make_xlsx, make_grade):
    grade = make_grade('JEAN DUPONT', 60)
    _, result = run_import(editor, source_file, make_xlsx, [('Jean Dupont', None, '7 EB A', 'Secondaire', '2024-2025')])
    grade.refresh_from_db()
    assert grade.percentage == Decimal('60.00') and result['unchanged'] == 1


def test_identical_value_is_left_untouched(editor, source_file, make_xlsx, make_grade):
    make_grade('JEAN DUPONT', 75)
    _, result = run_import(editor, source_file, make_xlsx, [ROW])
    assert result['unchanged'] == 1 and not ImportChange.objects.exists()


def test_dry_run_predicts_what_the_import_will_do(editor, source_file, make_xlsx, make_grade):
    make_grade('JEAN DUPONT', 60)                                  # sera mis à jour
    make_grade('MARIE KASONGO', 70, is_verified=True)              # sera bloqué
    make_grade('PAUL MBUYI', 50)                                   # inchangé
    rows = [ROW,
            ('Marie Kasongo', 90, '7 EB A', 'Secondaire', '2024-2025'),
            ('Paul Mbuyi', 50, '7 EB A', 'Secondaire', '2024-2025'),
            ('Nouvel Élève', 40, '7 EB A', 'Secondaire', '2024-2025')]
    path = make_xlsx(rows)
    report = dry_run(path)
    assert report['status'] == 'warning'     # une note vérifiée sera ignorée
    assert (report['to_create'], report['to_update'], report['unchanged'], report['blocked']) == (1, 1, 1, 1)
    assert not ImportChange.objects.exists() and Student.objects.count() == 3   # rien n'a été écrit

    sf = source_file(editor, path)
    result = do_import(sf.file.path, sf)
    assert (result['created'], result['updated'], result['unchanged'], result['blocked']) == (1, 1, 1, 1)


def test_dry_run_of_a_clean_file_is_ok(make_xlsx):
    assert dry_run(make_xlsx([ROW]))['status'] == 'ok'


def test_dry_run_reports_unreadable_files_without_leaking_details(tmp_path):
    bad = tmp_path / 'x.xlsx'
    bad.write_text('pas du tout un classeur')
    report = dry_run(str(bad))
    assert report['status'] == 'error' and report['valid_rows'] == 0
    assert str(tmp_path) not in report['message']


def test_dry_run_missing_columns(make_xlsx):
    report = dry_run(make_xlsx([('A', 1)], headers=['Nom complet', 'Pourcentage']))
    assert report['status'] == 'error'
    assert set(report['missing_columns']) == {'Classe', 'Section', 'Année scolaire'}


# ── Atomicité ────────────────────────────────────────────────────

def test_a_failure_in_the_middle_leaves_the_database_untouched(editor, source_file, make_xlsx, monkeypatch):
    path = make_xlsx([ROW, ('Marie Kasongo', 82, '7 EB A', 'Secondaire', '2024-2025')])
    sf = source_file(editor, path)
    real_create = GradeRecord.objects.create
    calls = []

    def flaky(**kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError('panne')
        return real_create(**kwargs)

    monkeypatch.setattr(GradeRecord.objects, 'create', flaky)
    with pytest.raises(RuntimeError):
        do_import(sf.file.path, sf)
    monkeypatch.undo()
    assert not GradeRecord.objects.exists() and not Student.objects.exists()


# ── Annulation ───────────────────────────────────────────────────

def test_rollback_deletes_created_grades_and_restores_modified_ones(editor, source_file, make_xlsx, make_grade):
    old = make_grade('MARIE KASONGO', 60)
    sf, _ = run_import(editor, source_file, make_xlsx, [
        ROW, ('Marie Kasongo', 90, '7 EB A', 'Secondaire', '2024-2025'),
    ])
    assert GradeRecord.objects.count() == 2

    result = rollback_import(sf)

    assert result == {'deleted': 1, 'restored': 1, 'kept': 0}
    old.refresh_from_db()
    assert old.percentage == Decimal('60.00')              # la note d'avant l'import est revenue
    assert list(GradeRecord.objects.values_list('student__full_name', flat=True)) == ['MARIE KASONGO']
    assert not SourceFile.objects.exists() and not ImportChange.objects.exists()


def test_rollback_does_not_destroy_an_editors_later_correction(editor, source_file, make_xlsx, make_grade):
    grade = make_grade('JEAN DUPONT', 60)
    sf, _ = run_import(editor, source_file, make_xlsx, [ROW])        # 60 -> 75
    GradeRecord.objects.filter(pk=grade.pk).update(percentage=Decimal('80'))   # correction manuelle

    result = rollback_import(sf)

    grade.refresh_from_db()
    assert grade.percentage == Decimal('80.00') and result['kept'] == 1 and result['restored'] == 0


def test_rollback_leaves_verified_modified_grades_alone(editor, source_file, make_xlsx, make_grade):
    grade = make_grade('JEAN DUPONT', 60)
    sf, _ = run_import(editor, source_file, make_xlsx, [ROW])
    GradeRecord.objects.filter(pk=grade.pk).update(is_verified=True)

    assert rollback_import(sf)['kept'] == 1
    grade.refresh_from_db()
    assert grade.percentage == Decimal('75.00')
