import re

import pytest
from django.urls import reverse

from apps.academics.models import AcademicYear, ClassRoom, Student
from apps.audit.utils import log_action
from apps.core.pagination import paginate
from apps.imports.models import SourceFile

pytestmark = pytest.mark.django_db


def links(response):
    return re.findall(r'href="([^"]*page=\d+[^"]*)"', response.content.decode())


# ── Le composant ─────────────────────────────────────────────────

def test_invalid_page_numbers_never_raise(rf):
    for value in ('abc', '0', '-3', '999', ''):
        request = rf.get('/', {'page': value})
        page = paginate(request, list(range(30)), 10)
        assert 1 <= page.number <= 3


def test_page_numbers_are_elided_for_long_lists(rf):
    page = paginate(rf.get('/', {'page': 10}), list(range(500)), 10)
    assert page.page_numbers[0] == 1 and page.page_numbers[-1] == 50 and None in page.page_numbers
    assert 10 in page.page_numbers and len(page.page_numbers) < 12


def test_no_pagination_bar_when_everything_fits_on_one_page(make_grade, as_user, reader):
    make_grade('A', 50)
    assert 'aria-label="Pagination"' not in as_user(reader).get(reverse('academics:student_list')).content.decode()


# ── Liste des élèves ─────────────────────────────────────────────

@pytest.fixture
def many_students(db):
    Student.objects.bulk_create([Student(full_name=f'A&B {i:02d}', name_key=f'A&B {i:02d}') for i in range(35)])


def test_student_list_is_paginated_and_keeps_the_search_encoded(many_students, as_user, reader):
    client = as_user(reader)
    first = client.get(reverse('academics:student_list'), {'q': 'a&b'})
    assert len(first.context['page_obj']) == 30 and first.context['total_count'] == 35
    next_links = [l for l in links(first) if 'page=2' in l]
    assert next_links and all('q=a%26b' in l for l in next_links)       # « & » ne casse plus l'URL
    second = client.get(reverse('academics:student_list'), {'q': 'a&b', 'page': 2})
    assert len(second.context['page_obj']) == 5


def test_student_list_htmx_navigation_targets_the_container(many_students, as_user, reader):
    response = as_user(reader).get(reverse('academics:student_list'), HTTP_HX_REQUEST='true')
    html = response.content.decode()
    assert 'hx-target="#student-container"' in html and 'hx-push-url="true"' in html


# ── Résultats d'une classe ───────────────────────────────────────

@pytest.fixture
def big_class(make_grade):
    for i in range(1, 61):
        make_grade(f'ELEVE {i:02d}', i)               # 60 résultats, tous différents
    return AcademicYear.objects.get().pk, ClassRoom.objects.get().pk


def test_results_table_ranks_are_global_not_per_page(big_class, as_user, editor):
    year, room = big_class
    client = as_user(editor)
    url = reverse('academics:results_table', args=big_class)
    page1 = client.get(url)
    page2 = client.get(url, {'page': 2})
    assert [r for r, _ in page1.context['rows']][:2] == [1, 2] and len(page1.context['rows']) == 50
    assert [r for r, _ in page2.context['rows']] == list(range(51, 61))
    assert page1.context['stats']['total'] == 60              # les statistiques portent sur toute la classe
    assert 'hx-target="#results-container"' in page1.content.decode()


def test_class_palmares_is_paginated(big_class, as_user, editor):
    response = as_user(editor).get(reverse('dashboard:class_palmares', args=big_class), {'page': 2})
    assert len(response.context['rows']) == 10 and response.context['stats']['total'] == 60


def test_exports_are_never_paginated(big_class, as_user, reader):
    csv_rows = as_user(reader).get(reverse('exports:csv_palmares', args=big_class)).content.decode('utf-8-sig').strip().splitlines()
    assert len(csv_rows) == 61


# ── Autres tableaux ──────────────────────────────────────────────

def test_year_dashboard_paginates_classes(make_grade, as_user, editor):
    for i in range(30):
        make_grade('ELEVE', 50, classroom=f'CLASSE {i:02d}')
    year = AcademicYear.objects.get()
    response = as_user(editor).get(reverse('dashboard:year_dashboard', args=[year.pk]))
    assert len(response.context['classes']) == 25
    assert 'Nb classes' in response.content.decode() and '>30<' in response.content.decode()   # total, pas la taille de la page


def test_home_paginates_years(make_grade, as_user, editor):
    for i in range(20):
        make_grade('ELEVE', 50, year=f'{2000 + i}-{2001 + i}')
    response = as_user(editor).get(reverse('dashboard:home'))
    assert len(response.context['years']) == 15 and response.context['years'].paginator.count == 20


def test_student_detail_paginates_results(make_grade, as_user, reader):
    for i in range(20):
        make_grade('ELEVE', 50, year=f'{2000 + i}-{2001 + i}')
    student = Student.objects.get()
    client = as_user(reader)
    response = client.get(reverse('academics:student_detail', args=[student.pk]))
    assert len(response.context['grades']) == 15 and '20 résultats enregistrés' in response.content.decode()
    assert len(client.get(reverse('academics:student_detail', args=[student.pk]), {'page': 2}).context['grades']) == 5


def test_audit_log_pagination_keeps_filters(admin, as_user):
    for i in range(60):
        log_action(admin, 'update', 'Student', i + 1)
    log_action(admin, 'verify', 'GradeRecord', 1)
    client = as_user(admin)
    response = client.get(reverse('dashboard:audit_log'), {'action': 'update'})
    assert len(response.context['page']) == 50
    assert all('action=update' in l for l in links(response))
    assert len(client.get(reverse('dashboard:audit_log'), {'action': 'update', 'page': 2}).context['page']) == 10


def test_import_list_is_paginated_and_polling_keeps_the_page(editor, as_user):
    import uuid
    batch = uuid.uuid4()
    SourceFile.objects.bulk_create([
        SourceFile(imported_by=editor, original_filename=f'f{i}.xlsx', file='imports/x.xlsx', batch_id=batch,
                   status=SourceFile.STATUS_PROCESSING)
        for i in range(30)
    ])
    client = as_user(editor)
    page2 = client.get(reverse('imports:import_list'), {'batch': batch, 'page': 2})
    assert len(page2.context['files']) == 5 and page2.context['files'].paginator.count == 30
    rows = client.get(reverse('imports:import_list_rows'), {'batch': batch, 'page': 2}).content.decode()
    assert f'batch={batch}&amp;page=2' in rows or f'batch={batch}&page=2' in rows        # le rafraîchissement reste sur la page 2
    # les liens de pagination visent la vraie page, pas l'endpoint de rafraîchissement
    assert all(l.startswith('/imports/?') for l in links(client.get(reverse('imports:import_list_rows'), {'batch': batch})))
    assert page2.context['batch_stats']['total'] == 30
