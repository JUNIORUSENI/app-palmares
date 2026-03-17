from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views.decorators.http import require_POST

from apps.accounts.mixins import editor_required
from .models import SourceFile
from .forms import SourceFileUploadForm
from .tasks import task_dry_run, task_import


@editor_required
def import_list(request):
    files = SourceFile.objects.select_related('academic_year', 'imported_by').all()
    return render(request, 'imports/import_list.html', {'files': files})


@editor_required
def import_upload(request):
    if request.method == 'POST':
        form = SourceFileUploadForm(request.POST, request.FILES)
        if form.is_valid():
            source_file = form.save(commit=False)
            source_file.imported_by = request.user
            source_file.original_filename = request.FILES['file'].name
            source_file.save()
            task_dry_run.delay(source_file.pk)
            messages.info(request, "Fichier uploadé. Analyse en cours, patientez...")
            return redirect('imports:import_dry_run', pk=source_file.pk)
    else:
        form = SourceFileUploadForm()
    columns = ['Nom complet', 'Pourcentage', 'Classe', 'Section', 'Année scolaire']
    return render(request, 'imports/import_upload.html', {'form': form, 'columns': columns})


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
    # Seul l'importateur ou un admin peut confirmer
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
