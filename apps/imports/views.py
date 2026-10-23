import logging
import os
import uuid

from django.conf import settings
from django.contrib import messages
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods

from apps.accounts.mixins import editor_required
from apps.audit.utils import log_action
from apps.core.pagination import paginate
from .excel import EXPECTED_COLUMNS, looks_like_excel
from .models import STALE_AFTER, SourceFile
from .services import rollback_import
from .tasks import task_dry_run, task_import

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'.xlsx', '.xls'}
IMPORTS_PAGE_SIZE = 25
UNAVAILABLE = "Le service de traitement est momentanément indisponible. Réessayez dans un instant."


def _megabytes(size):
    return f"{size // (1024 * 1024)} Mo"


def _validate_uploaded_file(f):
    """Retourne un message d'erreur ou None si valide."""
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return f"« {f.name} » : format non accepté (xlsx/xls uniquement)."
    if f.size > settings.IMPORT_MAX_FILE_SIZE:
        return f"« {f.name} » : fichier trop volumineux (max {_megabytes(settings.IMPORT_MAX_FILE_SIZE)})."
    head = f.read(8)
    f.seek(0)
    if not looks_like_excel(head):
        return f"« {f.name} » : ce n'est pas un vrai fichier Excel."
    return None


def _can_manage(user, source_file):
    """Seul l'auteur d'un import (ou un admin) peut le confirmer, le relancer ou l'annuler."""
    return user.is_admin or source_file.imported_by_id == user.pk


def _enqueue_dry_run(source_file, countdown=0):
    """Met l'analyse en file. Si le broker est indisponible, le fichier passe en erreur
    au lieu de rester « en attente » indéfiniment."""
    try:
        task_dry_run.apply_async(args=[source_file.pk], countdown=countdown)
    except Exception:
        logger.exception("Impossible de mettre l'analyse %s en file", source_file.pk)
        source_file.mark(
            SourceFile.STATUS_ERROR,
            dry_run_report={'status': 'error', 'message': UNAVAILABLE},
        )
        return False
    return True


def _batch_context(request):
    batch_id = request.GET.get('batch')
    files = SourceFile.objects.select_related('academic_year', 'imported_by').all()

    batch_stats = None
    if batch_id:
        try:
            files = files.filter(batch_id=uuid.UUID(batch_id))
        except (ValueError, AttributeError):
            batch_id = None
        else:
            fresh = timezone.now() - STALE_AFTER
            processing = files.filter(status=SourceFile.STATUS_PROCESSING)
            waiting = files.filter(status=SourceFile.STATUS_PENDING, dry_run_report={})
            batch_stats = {
                'batch_id': batch_id,
                'total': files.count(),
                'done': files.filter(status=SourceFile.STATUS_DONE).count(),
                'pending': files.filter(status=SourceFile.STATUS_PENDING).count(),
                'processing': processing.count(),
                'error': files.filter(status=SourceFile.STATUS_ERROR).count(),
                # Un fichier bloqué depuis longtemps ne doit pas maintenir l'actualisation automatique
                'has_active': (
                    processing.filter(updated_at__gte=fresh).exists()
                    or waiting.filter(updated_at__gte=fresh).exists()
                ),
            }
    return {
        'files': paginate(request, files, IMPORTS_PAGE_SIZE),
        'batch_stats': batch_stats,
        'batch_id': batch_id,
        # Le partiel rechargé par HTMX est servi par une autre URL : les liens de pagination visent la vraie page
        'import_list_url': reverse('imports:import_list'),
    }


@editor_required
def import_list(request):
    return render(request, 'imports/import_list.html', _batch_context(request))


@editor_required
def import_list_rows(request):
    """Endpoint HTMX — rafraîchissement du tableau (vue batch)."""
    return render(request, 'imports/partials/import_list_rows.html', _batch_context(request))


@editor_required
def import_upload(request):
    if request.method == 'POST':
        uploaded_files = request.FILES.getlist('file')

        if not uploaded_files:
            messages.error(request, "Aucun fichier sélectionné.")
            return redirect('imports:import_upload')

        if len(uploaded_files) > settings.IMPORT_MAX_FILES:
            messages.error(request, f"Maximum {settings.IMPORT_MAX_FILES} fichiers par lot.")
            return redirect('imports:import_upload')

        if sum(f.size for f in uploaded_files) > settings.IMPORT_MAX_BATCH_SIZE:
            messages.error(request, f"Lot trop volumineux (max {_megabytes(settings.IMPORT_MAX_BATCH_SIZE)} au total).")
            return redirect('imports:import_upload')

        # Valider tous les fichiers avant d'en créer un seul
        errors = [err for err in map(_validate_uploaded_file, uploaded_files) if err]
        if errors:
            for err in errors[:5]:  # afficher max 5 erreurs
                messages.error(request, err)
            return redirect('imports:import_upload')

        # Cas : un seul fichier → comportement classique (redirect dry-run)
        if len(uploaded_files) == 1:
            f = uploaded_files[0]
            source_file = SourceFile.objects.create(
                imported_by=request.user,
                original_filename=f.name[:255],
                file=f,
            )
            if _enqueue_dry_run(source_file):
                messages.info(request, "Fichier uploadé. Analyse en cours, patientez…")
            else:
                messages.error(request, UNAVAILABLE)
            return redirect('imports:import_dry_run', pk=source_file.pk)

        # Cas : plusieurs fichiers → batch
        batch_uuid = uuid.uuid4()
        queued = 0
        for index, f in enumerate(uploaded_files):
            source_file = SourceFile.objects.create(
                imported_by=request.user,
                original_filename=f.name[:255],
                file=f,
                batch_id=batch_uuid,
            )
            # Étalement des tâches : 5 s d'écart entre chaque
            if _enqueue_dry_run(source_file, countdown=index * 5):
                queued += 1

        if queued == len(uploaded_files):
            messages.success(request, f"{queued} fichier(s) mis en file d'attente pour analyse.")
        else:
            messages.error(request, f"{len(uploaded_files) - queued} fichier(s) n'ont pas pu être mis en file : {UNAVAILABLE}")
        return redirect(f"{reverse('imports:import_list')}?batch={batch_uuid}")

    return render(request, 'imports/import_upload.html', {
        'columns': EXPECTED_COLUMNS,
        'max_files': settings.IMPORT_MAX_FILES,
        'max_file_mb': settings.IMPORT_MAX_FILE_SIZE // (1024 * 1024),
        'max_batch_mb': settings.IMPORT_MAX_BATCH_SIZE // (1024 * 1024),
    })


@editor_required
def import_dry_run(request, pk):
    source_file = get_object_or_404(SourceFile, pk=pk)
    return render(request, 'imports/dry_run_report.html', {'source_file': source_file})


@editor_required
def import_dry_run_status(request, pk):
    """Endpoint HTMX — polling du résultat du dry-run."""
    source_file = get_object_or_404(SourceFile, pk=pk)
    return render(request, 'imports/partials/dry_run_status.html', {'source_file': source_file})


@editor_required
@require_POST
def import_confirm(request, pk):
    source_file = get_object_or_404(SourceFile, pk=pk)
    if not _can_manage(request.user, source_file):
        messages.error(request, "Vous ne pouvez confirmer que vos propres imports.")
        return redirect('imports:import_list')
    if source_file.status != SourceFile.STATUS_PENDING or not source_file.is_analyzed:
        messages.error(request, "Ce fichier n'est pas prêt à être importé.")
        return redirect('imports:import_dry_run', pk=pk)

    # Transition atomique : si deux clics arrivent en même temps, un seul lance l'import
    claimed = SourceFile.objects.filter(pk=pk, status=SourceFile.STATUS_PENDING).update(
        status=SourceFile.STATUS_PROCESSING, updated_at=timezone.now(),
    )
    if not claimed:
        return redirect('imports:import_progress', pk=pk)

    try:
        task_import.delay(source_file.pk)
    except Exception:
        logger.exception("Impossible de mettre l'import %s en file", pk)
        SourceFile.objects.filter(pk=pk).update(
            status=SourceFile.STATUS_PENDING, updated_at=timezone.now(),
        )
        messages.error(request, UNAVAILABLE)
        return redirect('imports:import_dry_run', pk=pk)
    return redirect('imports:import_progress', pk=pk)


@editor_required
@require_POST
def import_retry(request, pk):
    """Relance l'analyse d'un fichier en erreur ou bloqué."""
    source_file = get_object_or_404(SourceFile, pk=pk)
    if not _can_manage(request.user, source_file):
        messages.error(request, "Vous ne pouvez relancer que vos propres imports.")
        return redirect('imports:import_list')
    if source_file.status != SourceFile.STATUS_ERROR and not source_file.is_stale:
        messages.error(request, "Ce fichier n'a pas besoin d'être relancé.")
        return redirect('imports:import_dry_run', pk=pk)

    source_file.mark(SourceFile.STATUS_PENDING, dry_run_report={}, import_report={})
    if _enqueue_dry_run(source_file):
        messages.info(request, "Nouvelle analyse en cours…")
    else:
        messages.error(request, UNAVAILABLE)
    return redirect('imports:import_dry_run', pk=pk)


@editor_required
def import_progress(request, pk):
    source_file = get_object_or_404(SourceFile, pk=pk)
    return render(request, 'imports/import_progress.html', {'source_file': source_file})


@editor_required
def import_status(request, pk):
    """Endpoint HTMX — polling de l'état d'un import."""
    source_file = get_object_or_404(SourceFile, pk=pk)
    return render(request, 'imports/partials/import_status.html', {'source_file': source_file})


@editor_required
@require_http_methods(['GET', 'POST'])
def import_rollback(request, pk):
    source_file = get_object_or_404(SourceFile, pk=pk)
    if not _can_manage(request.user, source_file):
        messages.error(request, "Vous ne pouvez annuler que vos propres imports.")
        return redirect('imports:import_list')
    if source_file.status == SourceFile.STATUS_PROCESSING and not source_file.is_stale:
        messages.error(request, "Cet import est en cours de traitement : attendez qu'il se termine.")
        return redirect('imports:import_list')

    created = source_file.grade_records.all()
    grade_count = created.count()
    restore_count = source_file.changes.count()

    if request.method == 'POST':
        source_pk = source_file.pk
        filename = source_file.original_filename
        batch_id = source_file.batch_id
        old_value = {
            'original_filename': filename,
            'academic_year': str(source_file.academic_year) if source_file.academic_year else None,
            'grade_count': grade_count,
            'restore_count': restore_count,
            'imported_rows': source_file.imported_rows,
        }
        result = rollback_import(source_file)
        log_action(request.user, 'delete', 'SourceFile', source_pk,
                   old_value=old_value, new_value=result, object_repr=filename)
        messages.success(
            request,
            f"Import « {filename} » annulé : {result['deleted']} résultat(s) supprimé(s), "
            f"{result['restored']} valeur(s) restaurée(s)."
        )
        if batch_id:
            return redirect(f"{reverse('imports:import_list')}?batch={batch_id}")
        return redirect('imports:import_list')

    return render(request, 'imports/import_rollback.html', {
        'source_file': source_file,
        'grade_count': grade_count,
        'restore_count': restore_count,
        'verified_count': created.filter(is_verified=True).count(),
        # Anciens imports (avant le suivi des modifications) : on ne sait pas distinguer
        # les notes créées de celles qui ont été écrasées.
        'legacy': source_file.status == SourceFile.STATUS_DONE and 'created' not in (source_file.import_report or {}),
    })
