import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from apps.audit.utils import log_action

from .models import SourceFile
from .services import dry_run, do_import

logger = logging.getLogger(__name__)

GENERIC_ERROR = "Une erreur inattendue est survenue. Réessayez ou contactez un administrateur."


@shared_task(bind=True, soft_time_limit=300, time_limit=360)
def task_dry_run(self, source_file_id):
    try:
        source_file = SourceFile.objects.get(pk=source_file_id)
    except SourceFile.DoesNotExist:
        return  # import annulé entre-temps

    source_file.mark(SourceFile.STATUS_PROCESSING)
    try:
        report = dry_run(source_file.file.path)
    except SoftTimeLimitExceeded:
        source_file.mark(
            SourceFile.STATUS_ERROR,
            dry_run_report={'status': 'error', 'message': "Délai dépassé lors de l'analyse du fichier."},
        )
        return
    except Exception:
        logger.exception("Analyse du fichier %s en échec", source_file_id)
        source_file.mark(
            SourceFile.STATUS_ERROR,
            dry_run_report={'status': 'error', 'message': GENERIC_ERROR},
        )
        return

    # Un fichier illisible passe en erreur ; un fichier analysé attend la confirmation
    status = SourceFile.STATUS_ERROR if report.get('status') == 'error' else SourceFile.STATUS_PENDING
    source_file.mark(status, dry_run_report=report, total_rows=report.get('total_rows', 0))
    return report


@shared_task(bind=True, soft_time_limit=300, time_limit=360)
def task_import(self, source_file_id):
    try:
        source_file = SourceFile.objects.select_related('imported_by').get(pk=source_file_id)
    except SourceFile.DoesNotExist:
        return

    source_file.mark(SourceFile.STATUS_PROCESSING)
    try:
        result = do_import(source_file.file.path, source_file, task=self)
    except SoftTimeLimitExceeded:
        source_file.mark(
            SourceFile.STATUS_ERROR,
            import_report={'error': "Délai dépassé lors de l'import du fichier."},
        )
        return
    except Exception:
        logger.exception("Import du fichier %s en échec", source_file_id)
        source_file.mark(SourceFile.STATUS_ERROR, import_report={'error': GENERIC_ERROR})
        return

    source_file.mark(
        SourceFile.STATUS_DONE,
        imported_rows=result['imported'],
        error_rows=result['skipped'],
        import_report=result,
    )
    log_action(
        source_file.imported_by, 'import', 'SourceFile', source_file.pk,
        new_value={key: result[key] for key in ('total', 'created', 'updated', 'unchanged', 'blocked', 'skipped')},
        object_repr=source_file.original_filename,
    )
    return result
