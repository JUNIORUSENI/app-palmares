from decimal import Decimal

import pytest
from django.urls import reverse

from apps.academics.models import AcademicYear, ClassRoom, GradeRecord, Student
from apps.academics.services import MergeError, grade_summary, merge_students, ranked_grades, class_grades
from apps.audit.models import AuditLog

pytestmark = pytest.mark.django_db


def messages_of(response):
    return [str(m) for m in response.wsgi_request._messages]


# ── Modèle ───────────────────────────────────────────────────────

def test_student_name_key_follows_the_name():
    student = Student.objects.create(full_name='Ndayé  Mukendi')
    assert student.name_key == 'NDAYE MUKENDI'
    student.full_name = 'KABILA Joseph'
    student.save(update_fields=['full_name'])          # l'édition inline n'enregistre que ce champ
    student.refresh_from_db()
    assert student.name_key == 'KABILA JOSEPH'


# ── Classement et statistiques ───────────────────────────────────

def test_ungraded_students_come_last_and_ties_share_a_rank(make_grade):
    make_grade('SANS NOTE', None)
    make_grade('ALPHA', 80)
    make_grade('BETA', 90)
    make_grade('GAMMA', 80)
    make_grade('DELTA', 40)
    year, room = AcademicYear.objects.get(), ClassRoom.objects.get()

    rows = ranked_grades(class_grades(year, room))

    assert [(rank, g.student.full_name) for rank, g in rows] == [
        (1, 'BETA'), (2, 'ALPHA'), (2, 'GAMMA'), (4, 'DELTA'), (None, 'SANS NOTE'),
    ]


def test_pass_rate_is_computed_on_graded_students_only(make_grade):
    make_grade('A', 80)
    make_grade('B', 40)
    make_grade('C', 50)
    make_grade('SANS NOTE', None)
    stats = grade_summary(GradeRecord.objects.all())
    assert (stats['total'], stats['graded'], stats['passed'], stats['failed'], stats['ungraded']) == (4, 3, 2, 1, 1)
    assert stats['pass_rate'] == pytest.approx(66.7)


def test_pass_rate_is_none_when_nobody_is_graded(make_grade):
    make_grade('A', None)
    assert grade_summary(GradeRecord.objects.all())['pass_rate'] is None
    assert grade_summary(GradeRecord.objects.none())['pass_rate'] is None


def test_class_palmares_page(make_grade, as_user, editor):
    make_grade('SANS NOTE', None)
    make_grade('ALPHA', 80)
    make_grade('DELTA', 40)
    year, room = AcademicYear.objects.get(), ClassRoom.objects.get()
    response = as_user(editor).get(reverse('dashboard:class_palmares', args=[year.pk, room.pk]))
    assert response.status_code == 200
    assert [g.student.full_name for _, g in response.context['rows']] == ['ALPHA', 'DELTA', 'SANS NOTE']
    assert response.context['stats']['pass_rate'] == 50.0


def test_results_table_and_year_dashboard_agree_on_the_pass_rate(make_grade, as_user, editor):
    make_grade('A', 80)
    make_grade('B', 40)
    make_grade('SANS NOTE', None)
    year, room = AcademicYear.objects.get(), ClassRoom.objects.get()
    client = as_user(editor)
    table = client.get(reverse('academics:results_table', args=[year.pk, room.pk]))
    dashboard = client.get(reverse('dashboard:year_dashboard', args=[year.pk]))
    assert table.context['stats']['pass_rate'] == 50.0
    assert dashboard.context['pass_rate'] == 50.0


def test_results_index_builds_the_tree_in_few_queries(make_grade, as_user, editor, django_assert_max_num_queries):
    for year in ('2022-2023', '2023-2024', '2024-2025'):
        make_grade('A', 50, year=year)
    client = as_user(editor)
    with django_assert_max_num_queries(4):          # session + utilisateur + 1 requête pour tout l'arbre
        response = client.get(reverse('academics:results_index'))
    assert response.status_code == 200


# ── Fusion ───────────────────────────────────────────────────────

def test_merge_moves_grades_and_deletes_the_source(make_grade, as_user, editor):
    make_grade('DUPONT JEAN', 70, year='2023-2024')
    make_grade('DUPONT JEAN.', 80, year='2024-2025')
    source = Student.objects.get(full_name='DUPONT JEAN.')
    target = Student.objects.get(full_name='DUPONT JEAN')

    response = as_user(editor).post(reverse('academics:student_merge', args=[source.pk]), {'target_id': target.pk})

    assert response.status_code == 302
    assert not Student.objects.filter(pk=source.pk).exists()
    assert target.grades.count() == 2
    entry = AuditLog.objects.get(action='merge')
    assert entry.object_id == source.pk and entry.new_value['moved'] == 1


def test_merging_a_student_with_himself_changes_nothing(make_grade, as_user, editor):
    make_grade('DUPONT JEAN', 70)
    student = Student.objects.get()
    response = as_user(editor).post(reverse('academics:student_merge', args=[student.pk]), {'target_id': student.pk})
    assert response.status_code == 302
    assert Student.objects.filter(pk=student.pk).exists() and student.grades.count() == 1
    assert any('lui-même' in m for m in messages_of(response))
    assert not AuditLog.objects.exists()


@pytest.mark.parametrize('target', ['', 'abc', '999999', '1.5'])
def test_merge_with_a_bad_target_is_rejected_cleanly(make_grade, as_user, editor, target):
    make_grade('DUPONT JEAN', 70)
    student = Student.objects.get()
    response = as_user(editor).post(reverse('academics:student_merge', args=[student.pk]), {'target_id': target})
    assert response.status_code == 302
    assert Student.objects.filter(pk=student.pk).exists()


def test_merge_with_overlapping_grades_keeps_one_and_does_not_crash(make_grade, as_user, editor):
    make_grade('DUPONT JEAN', 70)
    make_grade('DUPONT JEAN.', 55)             # même classe, même année
    source = Student.objects.get(full_name='DUPONT JEAN.')
    target = Student.objects.get(full_name='DUPONT JEAN')

    response = as_user(editor).post(reverse('academics:student_merge', args=[source.pk]), {'target_id': target.pk})

    assert response.status_code == 302
    assert GradeRecord.objects.count() == 1 and GradeRecord.objects.get().percentage == Decimal('70.00')
    conflicts = AuditLog.objects.get(action='merge').new_value['conflicts']
    assert conflicts[0]['kept'] == '70.00' and conflicts[0]['dropped'] == '55.00'


def test_merge_fills_a_missing_grade_from_the_source(make_grade):
    make_grade('A', None)
    make_grade('B', 66)
    result = merge_students(Student.objects.get(full_name='B'), Student.objects.get(full_name='A'))
    assert GradeRecord.objects.get().percentage == Decimal('66.00') and len(result['conflicts']) == 1


def test_merge_prefers_the_verified_grade(make_grade, editor):
    make_grade('A', 50)
    make_grade('B', 66, is_verified=True, verified_by=editor)
    merge_students(Student.objects.get(full_name='B'), Student.objects.get(full_name='A'))
    grade = GradeRecord.objects.get()
    assert grade.percentage == Decimal('66.00') and grade.is_verified


def test_merge_service_refuses_self_merge(make_grade):
    make_grade('A', 50)
    student = Student.objects.get()
    with pytest.raises(MergeError):
        merge_students(student, student)
    assert GradeRecord.objects.count() == 1


def test_merge_page_suggests_similar_names_with_grade_counts(make_grade, as_user, editor, django_assert_max_num_queries):
    make_grade('KABASELE MARIE', 50)
    make_grade('KABASELE MARIA', 60)
    make_grade('TSHIMANGA PAUL', 70)
    source = Student.objects.get(full_name='KABASELE MARIE')
    client = as_user(editor)
    with django_assert_max_num_queries(5):          # session + utilisateur + élève + candidats (pas de N+1)
        response = client.get(reverse('academics:student_merge', args=[source.pk]))
    names = [c.full_name for c in response.context['candidates']]
    assert names == ['KABASELE MARIA']
    assert response.context['candidates'][0].grade_count == 1


def test_merge_page_does_not_crash_for_an_empty_name(as_user, editor):
    student = Student.objects.create(full_name='')
    assert as_user(editor).get(reverse('academics:student_merge', args=[student.pk])).status_code == 200


def test_merge_page_escapes_names_inside_javascript(make_grade, as_user, editor):
    make_grade("O'BRIEN\"); alert(1);//", 50)
    make_grade("O'BRIEN\"); alert(2);//.", 50, year='2023-2024')
    source = Student.objects.get(full_name__endswith='ALERT(1);//')
    page = as_user(editor).get(reverse('academics:student_merge', args=[source.pk])).content.decode()
    assert "');alert" not in page and '\\u0027' in page


def test_readers_cannot_merge(make_grade, as_user, reader):
    make_grade('A', 50)
    student = Student.objects.get()
    response = as_user(reader).post(reverse('academics:student_merge', args=[student.pk]), {'target_id': student.pk})
    assert response.status_code == 302 and 'students' in response.url


# ── Édition d'une note ───────────────────────────────────────────

@pytest.mark.parametrize('typed, expected', [('75,5', '75.50'), ('80', '80.00'), ('62 %', '62.00'), ('', None)])
def test_inline_edit_accepts_common_formats(make_grade, as_user, editor, typed, expected):
    grade = make_grade('A', 50, is_verified=True, verified_by=editor)
    as_user(editor).post(reverse('academics:grade_edit_inline', args=[grade.pk]), {'percentage': typed})
    grade.refresh_from_db()
    assert grade.percentage == (Decimal(expected) if expected else None)
    assert not grade.is_verified                      # une note modifiée doit être revérifiée
    entry = AuditLog.objects.get(action='update')
    assert entry.old_value == {'percentage': 50.0}


@pytest.mark.parametrize('typed', ['abc', '101', '-1', 'NaN', 'Infinity'])
def test_inline_edit_rejects_invalid_values(make_grade, as_user, editor, typed):
    grade = make_grade('A', 50)
    response = as_user(editor).post(reverse('academics:grade_edit_inline', args=[grade.pk]), {'percentage': typed})
    grade.refresh_from_db()
    assert grade.percentage == Decimal('50.00') and response.status_code == 200
    assert not AuditLog.objects.exists()


def test_readers_cannot_edit_a_grade(make_grade, as_user, reader):
    grade = make_grade('A', 50)
    as_user(reader).post(reverse('academics:grade_edit_inline', args=[grade.pk]), {'percentage': '99'})
    grade.refresh_from_db()
    assert grade.percentage == Decimal('50.00')


def test_verify_toggles_and_is_logged(make_grade, as_user, editor):
    grade = make_grade('A', 50)
    as_user(editor).post(reverse('academics:grade_verify', args=[grade.pk]))
    grade.refresh_from_db()
    assert grade.is_verified and grade.verified_by == editor and grade.verified_at
    assert AuditLog.objects.get(action='verify').new_value == {'is_verified': True}


def test_delete_student_is_logged_and_cascades(make_grade, as_user, editor):
    make_grade('A', 50)
    student = Student.objects.get()
    as_user(editor).post(reverse('academics:student_delete', args=[student.pk]))
    assert not Student.objects.exists() and not GradeRecord.objects.exists()
    assert AuditLog.objects.get(action='delete').old_value['grade_count'] == 1


def test_student_list_search_and_pagination(make_grade, as_user, reader):
    for i in range(35):
        make_grade(f'ELEVE {i:02d}', 50)
    client = as_user(reader)
    assert len(client.get(reverse('academics:student_list')).context['page_obj']) == 30
    assert client.get(reverse('academics:student_list') + '?page=zzz').status_code == 200
    assert client.get(reverse('academics:student_list') + '?q=ELEVE 07').context['total_count'] == 1
