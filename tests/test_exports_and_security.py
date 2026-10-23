import csv
import importlib
import io
from pathlib import Path

import pytest
from django.apps import apps as django_apps
from django.urls import reverse

from apps.academics.models import AcademicYear, ClassRoom, Student
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.audit.utils import log_action

pytestmark = pytest.mark.django_db
ROOT = Path(__file__).resolve().parent.parent


def parse_csv(response):
    text = response.content.decode('utf-8-sig')
    return list(csv.reader(io.StringIO(text), delimiter=';'))


@pytest.fixture
def class_ids(make_grade):
    make_grade('SANS NOTE', None)
    make_grade('ALPHA', 80)
    make_grade('BETA', 90)
    make_grade('GAMMA', 80)
    make_grade('DELTA', 40)
    return AcademicYear.objects.get().pk, ClassRoom.objects.get().pk


# ── Exports CSV ──────────────────────────────────────────────────

def test_csv_palmares_ranks_best_first_with_ties_and_ungraded_last(class_ids, as_user, reader):
    rows = parse_csv(as_user(reader).get(reverse('exports:csv_palmares', args=class_ids)))
    assert [(r[0], r[1], r[6]) for r in rows[1:]] == [
        ('1', 'BETA', 'Admis'), ('2', 'ALPHA', 'Admis'), ('2', 'GAMMA', 'Admis'),
        ('4', 'DELTA', 'Ajourné'), ('—', 'SANS NOTE', 'Non noté'),
    ]


def test_csv_uses_french_decimal_separator(class_ids, as_user, reader):
    rows = parse_csv(as_user(reader).get(reverse('exports:csv_palmares', args=class_ids)))
    assert rows[1][5] == '90,00'


def test_csv_neutralizes_spreadsheet_formulas(make_grade, as_user, reader):
    make_grade('=HYPERLINK("http://evil","clic")', 50)
    year, room = AcademicYear.objects.get(), ClassRoom.objects.get()
    for url in (reverse('exports:csv_palmares', args=[year.pk, room.pk]), reverse('exports:csv_students')):
        names = [r[1] if 'palmares' in url else r[0] for r in parse_csv(as_user(reader).get(url))[1:]]
        assert names == ['\'=HYPERLINK("HTTP://EVIL","CLIC")']


def test_csv_students_filters_and_ignores_bad_year(class_ids, as_user, reader):
    url = reverse('exports:csv_students')
    client = as_user(reader)
    assert len(parse_csv(client.get(url + '?q=alpha'))) == 2
    assert len(parse_csv(client.get(url + '?year=abc'))) == 6      # filtre ignoré, pas d'erreur 500


def test_csv_filename_is_sanitized(make_grade, as_user, reader):
    make_grade('A', 50, classroom='7"; evil=1')
    year, room = AcademicYear.objects.get(), ClassRoom.objects.get()
    response = as_user(reader).get(reverse('exports:csv_palmares', args=[year.pk, room.pk]))
    assert '"; evil' not in response['Content-Disposition']


# ── Exports PDF ──────────────────────────────────────────────────

def test_palmares_pdf_is_a_real_pdf(class_ids, as_user, reader):
    response = as_user(reader).get(reverse('exports:pdf_palmares', args=class_ids))
    assert response['Content-Type'] == 'application/pdf' and response.content.startswith(b'%PDF')


def test_palmares_pdf_counts_failed_and_ungraded_correctly(class_ids, as_user, reader):
    from django.template.loader import render_to_string
    from apps.academics.services import class_grades, grade_summary, ranked_grades
    year, room = AcademicYear.objects.get(), ClassRoom.objects.get()
    grades = class_grades(year, room)
    html = render_to_string('exports/palmares_pdf.html', {
        'year': year, 'classroom': room, 'rows': ranked_grades(grades), 'stats': grade_summary(grades),
    })
    assert 'None%' not in html and 'None' not in html
    assert '<div class="val" style="color:#dc2626">1</div>Ajournés' in html
    assert 'Non notés' in html


def test_student_pdf_handles_ungraded_results(make_grade, as_user, reader):
    make_grade('SANS NOTE', None)
    student = Student.objects.get()
    response = as_user(reader).get(reverse('exports:pdf_student', args=[student.pk]))
    assert response.content.startswith(b'%PDF')


# ── Comptes et droits ────────────────────────────────────────────

def test_superuser_is_an_application_admin():
    user = User.objects.create_superuser('root', 'root@example.org', 'motdepasse-solide-1')
    assert user.role == User.ROLE_ADMIN and user.is_admin


def test_promoting_a_user_to_superuser_also_promotes_the_role(reader):
    reader.is_superuser = True
    reader.save()
    reader.refresh_from_db()
    assert reader.role == User.ROLE_ADMIN


def test_data_migration_promotes_existing_superusers(db):
    migration = importlib.import_module('apps.accounts.migrations.0002_superusers_are_admins')
    User.objects.create_user('legacy', password='x', is_superuser=True, role=User.ROLE_READER)
    User.objects.filter(username='legacy').update(role=User.ROLE_READER)   # contourne le save()
    migration.promote_superusers(django_apps, None)
    assert User.objects.get(username='legacy').role == User.ROLE_ADMIN


def test_data_migration_fills_name_keys_for_existing_students(db):
    migration = importlib.import_module('apps.academics.migrations.0006_populate_student_name_key')
    Student.objects.create(full_name='Ndayé  Mukendi')
    Student.objects.update(name_key='')
    migration.populate_name_key(django_apps, None)
    assert Student.objects.get().name_key == 'NDAYE MUKENDI'


@pytest.mark.parametrize('name', ['dashboard:audit_log', 'dashboard:admin_stats'])
def test_admin_pages_are_closed_to_editors(editor, as_user, name):
    response = as_user(editor).get(reverse(name))
    assert response.status_code == 302


def test_audit_log_accepts_filters_and_ignores_garbage(admin, as_user):
    log_action(admin, 'update', 'Student', 1, object_repr='x')
    client = as_user(admin)
    assert len(client.get(reverse('dashboard:audit_log') + f'?user={admin.pk}').context['page']) == 1
    assert client.get(reverse('dashboard:audit_log') + '?user=abc').status_code == 200   # 500 auparavant


def test_audit_object_repr_is_truncated_instead_of_failing(admin):
    log_action(admin, 'update', 'Student', 1, object_repr='é' * 500)
    assert len(AuditLog.objects.get().object_repr) == 200


def test_password_reset_routes_are_not_exposed(client):
    assert client.get('/accounts/password_reset/').status_code == 404
    assert client.get('/accounts/login/').status_code == 200


def test_login_and_logout_work(client, editor):
    assert client.post('/accounts/login/', {'username': 'editor1', 'password': 'motdepasse-solide-1'}).status_code == 302
    assert client.post('/accounts/logout/').status_code == 302


def test_login_page_loads_without_any_cdn(client):
    page = client.get('/accounts/login/').content.decode()
    assert 'cdn.tailwindcss.com' not in page and '/static/css/app.css' in page


def test_session_is_not_rewritten_on_every_request(settings):
    assert settings.SESSION_SAVE_EVERY_REQUEST is False


# ── Fichiers de déploiement ──────────────────────────────────────

def test_uploaded_files_are_not_served_by_nginx():
    config = (ROOT / 'nginx' / 'nginx.conf').read_text(encoding='utf-8')
    assert 'alias /app/media' not in config
    assert 'location /media/ {\n        return 404;' in config


def test_nginx_csp_no_longer_allows_external_script_hosts():
    config = (ROOT / 'nginx' / 'nginx.conf').read_text(encoding='utf-8')
    csp = next(line for line in config.splitlines() if 'Content-Security-Policy' in line)
    for host in ('cdn.tailwindcss.com', 'unpkg.com', 'cdn.jsdelivr.net'):
        assert host not in csp
    assert "frame-ancestors 'none'" in csp


def test_nginx_rate_limit_uses_the_real_client_ip():
    config = (ROOT / 'nginx' / 'nginx.conf').read_text(encoding='utf-8')
    assert 'real_ip_header X-Forwarded-For' in config and 'set_real_ip_from' in config
    assert '(accounts/login|admin/login)' in config


def test_nginx_upload_limit_matches_django_batch_limit(settings):
    config = (ROOT / 'nginx' / 'nginx.conf').read_text(encoding='utf-8')
    limit_mb = int(next(line for line in config.splitlines() if 'client_max_body_size' in line).split()[1].rstrip('M;'))
    assert limit_mb * 1024 * 1024 > settings.IMPORT_MAX_BATCH_SIZE


def test_redis_never_evicts_queued_tasks():
    compose = (ROOT / 'docker-compose.prod.yml').read_text(encoding='utf-8')
    assert '--maxmemory-policy noeviction' in compose and '--maxmemory-policy allkeys-lru' not in compose
    assert 'redis_data' in compose and '--appendonly yes' in compose


def test_no_template_loads_scripts_from_a_cdn():
    for template in (ROOT / 'templates').rglob('*.html'):
        text = template.read_text(encoding='utf-8')
        for host in ('cdn.tailwindcss.com', 'unpkg.com', 'cdn.jsdelivr.net'):
            assert host not in text, f'{template.name} charge {host}'
