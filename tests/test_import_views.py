from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import GradeRecord, Student
from apps.audit.models import AuditLog
from apps.imports import views
from apps.imports.models import ImportChange, SourceFile

pytestmark = pytest.mark.django_db

ROW = ('Jean Dupont', 75, '7 EB A', 'Secondaire', '2024-2025')


def messages_of(response):
    return [str(m) for m in response.wsgi_request._messages]


def post_upload(client, upload, *paths):
    return client.post(reverse('imports:import_upload'), {'file': [upload(p, name=f'f{i}.xlsx') for i, p in enumerate(paths)]})


@pytest.fixture
def analyzed(editor, as_user, make_xlsx, upload):
    """Un fichier uploadé et analysé (Celery s'exécute immédiatement dans les tests)."""
    def _make(rows=(ROW,)):
        client = as_user(editor)
        post_upload(client, upload, make_xlsx(list(rows)))
        return SourceFile.objects.latest('pk')
    return _make


# ── Droits d'accès ───────────────────────────────────────────────

@pytest.mark.parametrize('name', ['imports:import_list', 'imports:import_upload'])
def test_readers_cannot_use_imports(reader, as_user, name):
    response = as_user(reader).get(reverse(name))
    assert response.status_code == 302 and 'students' in response.url


def test_anonymous_users_are_sent_to_login(client):
    response = client.get(reverse('imports:import_list'))
    assert response.status_code == 302 and 'login' in response.url


# ── Téléversement ────────────────────────────────────────────────

def test_upload_stores_the_file_under_an_unguessable_name(analyzed):
    sf = analyzed()
    assert sf.original_filename == 'f0.xlsx'
    assert sf.file.name.startswith('imports/') and 'f0.xlsx' not in sf.file.name and sf.file.name.endswith('.xlsx')
    assert sf.status == SourceFile.STATUS_PENDING and sf.is_analyzed


def test_upload_rejects_wrong_extension(editor, as_user, upload, make_xlsx):
    response = as_user(editor).post(reverse('imports:import_upload'), {'file': [upload(make_xlsx([ROW]), name='notes.pdf')]})
    assert response.status_code == 302
    assert not SourceFile.objects.exists()


def test_upload_rejects_a_fake_excel_file(editor, as_user, tmp_path, upload):
    fake = tmp_path / 'x.xlsx'
    fake.write_text('<?php echo "pwned"; ?>')
    response = as_user(editor).post(reverse('imports:import_upload'), {'file': [upload(str(fake))]})
    assert not SourceFile.objects.exists()
    assert any('vrai fichier Excel' in m for m in messages_of(response))


def test_upload_rejects_an_oversized_batch(editor, as_user, upload, make_xlsx, settings):
    settings.IMPORT_MAX_BATCH_SIZE = 1000
    response = post_upload(as_user(editor), upload, make_xlsx([ROW]), make_xlsx([ROW]))
    assert not SourceFile.objects.exists()
    assert any('Lot trop volumineux' in m for m in messages_of(response))


def test_upload_rejects_an_oversized_file(editor, as_user, upload, make_xlsx, settings):
    settings.IMPORT_MAX_FILE_SIZE = 1000
    post_upload(as_user(editor), upload, make_xlsx([ROW]))
    assert not SourceFile.objects.exists()


def test_batch_upload_creates_one_file_per_upload(editor, as_user, upload, make_xlsx):
    response = post_upload(as_user(editor), upload, make_xlsx([ROW]), make_xlsx([ROW]))
    assert SourceFile.objects.count() == 2
    assert len({sf.batch_id for sf in SourceFile.objects.all()}) == 1
    assert 'batch=' in response.url


def test_upload_when_the_queue_is_down_marks_the_file_as_error(editor, as_user, upload, make_xlsx, monkeypatch):
    def down(*args, **kwargs):
        raise ConnectionError('redis down')
    monkeypatch.setattr(views.task_dry_run, 'apply_async', down)
    response = post_upload(as_user(editor), upload, make_xlsx([ROW]))
    sf = SourceFile.objects.get()
    assert sf.status == SourceFile.STATUS_ERROR
    assert any('indisponible' in m for m in messages_of(response))


# ── Confirmation ─────────────────────────────────────────────────

def test_confirm_imports_the_file_and_logs_it(analyzed, as_user, editor):
    sf = analyzed()
    response = as_user(editor).post(reverse('imports:import_confirm', args=[sf.pk]))
    sf.refresh_from_db()
    assert response.status_code == 302
    assert sf.status == SourceFile.STATUS_DONE and sf.imported_rows == 1
    assert GradeRecord.objects.get().percentage == Decimal('75.00')
    entry = AuditLog.objects.get(action='import')
    assert entry.user == editor and entry.new_value['created'] == 1


def test_double_click_on_confirm_imports_only_once(analyzed, as_user, editor):
    sf = analyzed()
    client = as_user(editor)
    client.post(reverse('imports:import_confirm', args=[sf.pk]))
    second = client.post(reverse('imports:import_confirm', args=[sf.pk]))
    assert second.status_code == 302
    assert GradeRecord.objects.count() == 1 and AuditLog.objects.filter(action='import').count() == 1


def test_confirm_is_refused_while_the_import_is_already_running(analyzed, as_user, editor):
    sf = analyzed()
    SourceFile.objects.filter(pk=sf.pk).update(status=SourceFile.STATUS_PROCESSING)
    as_user(editor).post(reverse('imports:import_confirm', args=[sf.pk]))
    assert not GradeRecord.objects.exists()


def test_confirm_is_refused_before_the_analysis_is_finished(editor, as_user, source_file, make_xlsx):
    sf = source_file(editor, make_xlsx([ROW]))          # jamais analysé : dry_run_report vide
    as_user(editor).post(reverse('imports:import_confirm', args=[sf.pk]))
    sf.refresh_from_db()
    assert sf.status == SourceFile.STATUS_PENDING and not GradeRecord.objects.exists()


def test_confirm_is_refused_for_a_file_with_a_structural_error(editor, as_user, source_file, make_xlsx):
    sf = source_file(editor, make_xlsx([('A', 1)], headers=['Nom complet', 'Pourcentage']),
                     dry_run_report={'status': 'error', 'message': 'x'})
    as_user(editor).post(reverse('imports:import_confirm', args=[sf.pk]))
    assert not GradeRecord.objects.exists()


def test_confirm_requires_post(analyzed, as_user, editor):
    sf = analyzed()
    assert as_user(editor).get(reverse('imports:import_confirm', args=[sf.pk])).status_code == 405


def test_other_editors_cannot_confirm_or_rollback_but_admins_can(analyzed, as_user, editor2, admin):
    sf = analyzed()
    as_user(editor2).post(reverse('imports:import_confirm', args=[sf.pk]))
    assert not GradeRecord.objects.exists()
    as_user(editor2).post(reverse('imports:import_retry', args=[sf.pk]))
    assert as_user(editor2).get(reverse('imports:import_rollback', args=[sf.pk])).status_code == 302

    as_user(admin).post(reverse('imports:import_confirm', args=[sf.pk]))
    assert GradeRecord.objects.count() == 1


def test_confirm_when_the_queue_is_down_puts_the_file_back_to_pending(analyzed, as_user, editor, monkeypatch):
    sf = analyzed()

    def down(*args, **kwargs):
        raise ConnectionError('redis down')
    monkeypatch.setattr(views.task_import, 'delay', down)
    response = as_user(editor).post(reverse('imports:import_confirm', args=[sf.pk]))
    sf.refresh_from_db()
    assert sf.status == SourceFile.STATUS_PENDING and response.url.endswith('/dry-run/')


# ── Erreurs de traitement ────────────────────────────────────────

def test_analysis_crash_marks_the_file_as_error_without_leaking_details(editor, as_user, upload, make_xlsx, monkeypatch):
    def boom(path):
        raise RuntimeError('mot-de-passe-secret-de-la-base')
    monkeypatch.setattr('apps.imports.tasks.dry_run', boom)
    post_upload(as_user(editor), upload, make_xlsx([ROW]))
    sf = SourceFile.objects.get()
    assert sf.status == SourceFile.STATUS_ERROR
    assert 'secret' not in str(sf.dry_run_report)


def test_import_crash_marks_the_file_as_error_without_leaking_details(analyzed, as_user, editor, monkeypatch):
    sf = analyzed()

    def boom(*args, **kwargs):
        raise RuntimeError('mot-de-passe-secret-de-la-base')
    monkeypatch.setattr('apps.imports.tasks.do_import', boom)
    as_user(editor).post(reverse('imports:import_confirm', args=[sf.pk]))
    sf.refresh_from_db()
    assert sf.status == SourceFile.STATUS_ERROR and 'secret' not in str(sf.import_report)
    page = as_user(editor).get(reverse('imports:import_status', args=[sf.pk]))
    assert 'secret' not in page.content.decode()


def test_unreadable_file_ends_in_error_status(editor, as_user, upload, make_xlsx):
    post_upload(as_user(editor), upload, make_xlsx([('A', 1)], headers=['Nom complet', 'Pourcentage']))
    sf = SourceFile.objects.get()
    assert sf.status == SourceFile.STATUS_ERROR and 'Colonnes manquantes' in sf.dry_run_report['message']


def test_retry_after_an_error_analyses_the_file_again(editor, as_user, upload, make_xlsx, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr('apps.imports.tasks.dry_run', lambda path: (_ for _ in ()).throw(RuntimeError('x')))
        post_upload(as_user(editor), upload, make_xlsx([ROW]))
    sf = SourceFile.objects.get()
    assert sf.status == SourceFile.STATUS_ERROR

    as_user(editor).post(reverse('imports:import_retry', args=[sf.pk]))
    sf.refresh_from_db()
    assert sf.status == SourceFile.STATUS_PENDING and sf.is_analyzed


def test_retry_is_refused_for_a_healthy_file(analyzed, as_user, editor):
    sf = analyzed()
    response = as_user(editor).post(reverse('imports:import_retry', args=[sf.pk]))
    sf.refresh_from_db()
    assert sf.is_analyzed and response.status_code == 302


# ── Fichiers bloqués ─────────────────────────────────────────────

def make_stale(sf, minutes=11):
    SourceFile.objects.filter(pk=sf.pk).update(updated_at=timezone.now() - timedelta(minutes=minutes))
    sf.refresh_from_db()


def test_stale_detection(editor, source_file, make_xlsx):
    sf = source_file(editor, make_xlsx([ROW]), status=SourceFile.STATUS_PROCESSING)
    assert not sf.is_stale
    make_stale(sf, 9)
    assert not sf.is_stale
    make_stale(sf, 11)
    assert sf.is_stale
    SourceFile.objects.filter(pk=sf.pk).update(status=SourceFile.STATUS_DONE)
    sf.refresh_from_db()
    assert not sf.is_stale


def test_stuck_processing_file_shows_a_retry_button_and_can_be_restarted(editor, as_user, source_file, make_xlsx):
    sf = source_file(editor, make_xlsx([ROW]), status=SourceFile.STATUS_PROCESSING)
    make_stale(sf)
    page = as_user(editor).get(reverse('imports:import_dry_run_status', args=[sf.pk])).content.decode()
    assert 'semble bloqué' in page and reverse('imports:import_retry', args=[sf.pk]) in page

    as_user(editor).post(reverse('imports:import_retry', args=[sf.pk]))
    sf.refresh_from_db()
    assert sf.is_analyzed and not sf.is_stale


def test_a_stuck_file_does_not_keep_the_batch_page_polling_forever(editor, as_user, source_file, make_xlsx):
    import uuid
    batch = uuid.uuid4()
    sf = source_file(editor, make_xlsx([ROW]), status=SourceFile.STATUS_PROCESSING, batch_id=batch)
    url = reverse('imports:import_list_rows') + f'?batch={batch}'
    assert 'hx-trigger="every 3s"' in as_user(editor).get(url).content.decode()
    make_stale(sf)
    assert 'hx-trigger="every 3s"' not in as_user(editor).get(url).content.decode()


def test_invalid_batch_id_does_not_crash_the_list(editor, as_user):
    assert as_user(editor).get(reverse('imports:import_list') + '?batch=pas-un-uuid').status_code == 200


# ── Pages de rapport ─────────────────────────────────────────────

def test_dry_run_page_shows_the_breakdown_and_the_confirm_button(analyzed, as_user, editor, make_grade):
    make_grade('JEAN DUPONT', 60)
    sf = analyzed()
    page = as_user(editor).get(reverse('imports:import_dry_run_status', args=[sf.pk])).content.decode()
    assert 'Mises à jour' in page and reverse('imports:import_confirm', args=[sf.pk]) in page


def test_done_page_shows_the_breakdown(analyzed, as_user, editor):
    sf = analyzed()
    as_user(editor).post(reverse('imports:import_confirm', args=[sf.pk]))
    page = as_user(editor).get(reverse('imports:import_status', args=[sf.pk])).content.decode()
    assert '1 créé' in page


# ── Annulation d'un import ───────────────────────────────────────

def test_rollback_page_and_action(analyzed, as_user, editor, make_grade):
    old = make_grade('MARIE KASONGO', 60)
    sf = analyzed([ROW, ('Marie Kasongo', 90, '7 EB A', 'Secondaire', '2024-2025')])
    client = as_user(editor)
    client.post(reverse('imports:import_confirm', args=[sf.pk]))

    page = client.get(reverse('imports:import_rollback', args=[sf.pk]))
    assert page.status_code == 200
    assert page.context['grade_count'] == 1 and page.context['restore_count'] == 1 and not page.context['legacy']

    client.post(reverse('imports:import_rollback', args=[sf.pk]))
    old.refresh_from_db()
    assert old.percentage == Decimal('60.00')
    assert GradeRecord.objects.count() == 1
    entry = AuditLog.objects.filter(action='delete', model_name='SourceFile').get()
    assert entry.new_value['restored'] == 1 and entry.new_value['deleted'] == 1


def test_rollback_is_refused_while_processing(analyzed, as_user, editor):
    sf = analyzed()
    SourceFile.objects.filter(pk=sf.pk).update(status=SourceFile.STATUS_PROCESSING)
    as_user(editor).post(reverse('imports:import_rollback', args=[sf.pk]))
    assert SourceFile.objects.filter(pk=sf.pk).exists()


def test_rollback_of_a_legacy_import_warns_the_user(editor, as_user, source_file, make_xlsx):
    sf = source_file(editor, make_xlsx([ROW]), status=SourceFile.STATUS_DONE, import_report={'total': 1, 'imported': 1})
    page = as_user(editor).get(reverse('imports:import_rollback', args=[sf.pk]))
    assert page.context['legacy'] and 'Import ancien' in page.content.decode()


def test_rollback_with_a_very_long_filename_is_logged(analyzed, as_user, editor):
    sf = analyzed()
    SourceFile.objects.filter(pk=sf.pk).update(original_filename='x' * 250 + '.xlsx')
    as_user(editor).post(reverse('imports:import_rollback', args=[sf.pk]))
    assert len(AuditLog.objects.get(action='delete').object_repr) == 200
