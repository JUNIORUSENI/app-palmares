import os
import uuid

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.urls import reverse
from django.views.decorators.http import require_POST, require_http_methods

from apps.accounts.mixins import editor_required
from apps.audit.utils import log_action
from .models import SourceFile
from .tasks import task_dry_run, task_import

MAX_FILES = 100
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
ALLOWED_EXTENSIONS = {'.xlsx', '.xls'}


def _validate_uploaded_file(f):
    """Retourne un message d'erreur ou None si valide."""
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return f"« {f.name} » : format non accepté (xlsx/xls uniquement)."
    if f.size > MAX_FILE_SIZE:
        return f"« {f.name} » : fichier trop volumineux (max 20 Mo)."
    return None


@editor_required
def import_list(request):
    batch_id = request.GET.get('batch')
    files = SourceFile.objects.select_related('academic_year', 'imported_by').all()

    batch_stats = None
    if batch_id:
        try:
            batch_uuid = uuid.UUID(batch_id)
            files = files.filter(batch_id=batch_uuid)
            total = files.count()
            done = files.filter(status=SourceFile.STATUS_DONE).count()
            pending = files.filter(status=SourceFile.STATUS_PENDING).count()
            processing = files.filter(status=SourceFile.STATUS_PROCESSING).count()
            error = files.filter(status=SourceFile.STATUS_ERROR).count()
            batch_stats = {
                'batch_id': batch_id,
                'total': total,
                'done': done,
                'pending': pending,
                'processing': processing,
                'error': error,
                'has_active': (pending + processing) > 0,
            }
        except (ValueError, AttributeError):
            batch_id = None

    return render(request, 'imports/import_list.html', {
        'files': files,
        'batch_stats': batch_stats,
        'batch_id': batch_id,
    })


@editor_required
def import_list_rows(request):
    """Endpoint HTMX — rafraîchissement du tableau (vue batch)."""
    batch_id = request.GET.get('batch')
    files = SourceFile.objects.select_related('academic_year', 'imported_by').all()

    batch_stats = None
    if batch_id:
        try:
            batch_uuid = uuid.UUID(batch_id)
            files = files.filter(batch_id=batch_uuid)
            total = files.count()
            done = files.filter(status=SourceFile.STATUS_DONE).count()
            pending = files.filter(status=SourceFile.STATUS_PENDING).count()
            processing = files.filter(status=SourceFile.STATUS_PROCESSING).count()
            error = files.filter(status=SourceFile.STATUS_ERROR).count()
            batch_stats = {
                'batch_id': batch_id,
                'total': total,
                'done': done,
                'pending': pending,
                'processing': processing,
                'error': error,
                'has_active': (pending + processing) > 0,
            }
        except (ValueError, AttributeError):
            batch_id = None

    return render(request, 'imports/partials/import_list_rows.html', {
        'files': files,
        'batch_stats': batch_stats,
        'batch_id': batch_id,
    })


@editor_required
def import_upload(request):
    if request.method == 'POST':
        uploaded_files = request.FILES.getlist('file')

        if not uploaded_files:
            messages.error(request, "Aucun fichier sélectionné.")
            return redirect('imports:import_upload')

        if len(uploaded_files) > MAX_FILES:
            messages.error(request, f"Maximum {MAX_FILES} fichiers par lot.")
            return redirect('imports:import_upload')

        # Valider tous les fichiers avant d'en créer un seul
        errors = []
        for f in uploaded_files:
            err = _validate_uploaded_file(f)
            if err:
                errors.append(err)
        if errors:
            for err in errors[:5]:  # afficher max 5 erreurs
                messages.error(request, err)
            return redirect('imports:import_upload')

        # Cas : un seul fichier → comportement classique (redirect dry-run)
        if len(uploaded_files) == 1:
            f = uploaded_files[0]
            source_file = SourceFile(
                imported_by=request.user,
                original_filename=f.name,
                file=f,
            )
            source_file.save()
            task_dry_run.apply_async(args=[source_file.pk])
            messages.info(request, "Fichier uploadé. Analyse en cours, patientez…")
            return redirect('imports:import_dry_run', pk=source_file.pk)

        # Cas : plusieurs fichiers → batch
        batch_uuid = uuid.uuid4()
        created = []
        for index, f in enumerate(uploaded_files):
            source_file = SourceFile(
                imported_by=request.user,
                original_filename=f.name,
                file=f,
                batch_id=batch_uuid,
            )
            source_file.save()
            # Étalement des tâches : 5 s d'écart entre chaque
            task_dry_run.apply_async(args=[source_file.pk], countdown=index * 5)
            created.append(source_file)

        messages.success(
            request,
            f"{len(created)} fichier(s) mis en file d'attente pour analyse."
        )
        return redirect(f"{reverse('imports:import_list')}?batch={batch_uuid}")

    columns = ['Nom complet', 'Pourcentage', 'Classe', 'Section', 'Année scolaire']
    return render(request, 'imports/import_upload.html', {'columns': columns})


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
    if source_file.imported_by != request.user and not request.user.is_admin:
        messages.error(request, "Vous ne pouvez confirmer que vos propres imports.")
        return redirect('imports:import_list')
    if source_file.status != SourceFile.STATUS_PENDING:
        messages.error(request, "Ce fichier n'est pas prêt à être importé.")
        return redirect('imports:import_dry_run', pk=pk)
    task_import.delay(source_file.pk)
    return redirect('imports:import_progress', pk=pk)


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
    grades = source_file.grade_records.all()
    grade_count = grades.count()

    if request.method == 'POST':
        old_value = {
            'original_filename': source_file.original_filename,
            'academic_year': str(source_file.academic_year) if source_file.academic_year else None,
            'grade_count': grade_count,
            'imported_rows': source_file.imported_rows,
        }
        log_action(request.user, 'delete', 'SourceFile', source_file.pk,
                   old_value=old_value, object_repr=source_file.original_filename)
        batch_id = source_file.batch_id
        grades.delete()
        source_file.delete()
        messages.success(
            request,
            f"Import « {source_file.original_filename} » annulé : {grade_count} résultat(s) supprimé(s)."
        )
        if batch_id:
            return redirect(f"{reverse('imports:import_list')}?batch={batch_id}")
        return redirect('imports:import_list')

    return render(request, 'imports/import_rollback.html', {
        'source_file': source_file,
        'grade_count': grade_count,
    })
