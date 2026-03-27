from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from .services import dry_run, do_import


@shared_task(bind=True, soft_time_limit=300, time_limit=360)
def task_dry_run(self, source_file_id):
    from .models import SourceFile

    source_file = SourceFile.objects.get(pk=source_file_id)
    source_file.status = SourceFile.STATUS_PROCESSING
    source_file.save(update_fields=['status'])

    try:
        report = dry_run(source_file.file.path)
    except SoftTimeLimitExceeded:
        source_file.status = SourceFile.STATUS_ERROR
        source_file.dry_run_report = {'error': "Délai dépassé lors de l'analyse du fichier."}
        source_file.save(update_fields=['status', 'dry_run_report'])
        return

    source_file.dry_run_report = report
    source_file.total_rows = report.get('total_rows', 0)
    source_file.status = SourceFile.STATUS_PENDING
    source_file.save(update_fields=['dry_run_report', 'total_rows', 'status'])

    return report


@shared_task(bind=True, soft_time_limit=300, time_limit=360)
def task_import(self, source_file_id):
    from .models import SourceFile

    source_file = SourceFile.objects.get(pk=source_file_id)
    source_file.status = SourceFile.STATUS_PROCESSING
    source_file.save(update_fields=['status'])

    try:
        result = do_import(source_file.file.path, source_file, task=self)

        source_file.status = SourceFile.STATUS_DONE
        source_file.imported_rows = result['imported']
        source_file.error_rows = result['skipped']
        source_file.import_report = result
        source_file.save(update_fields=['status', 'imported_rows', 'error_rows', 'import_report'])

    except SoftTimeLimitExceeded:
        source_file.status = SourceFile.STATUS_ERROR
        source_file.import_report = {'error': "Délai dépassé lors de l'import du fichier."}
        source_file.save(update_fields=['status', 'import_report'])
        return

    except Exception as e:
        source_file.status = SourceFile.STATUS_ERROR
        source_file.import_report = {'error': str(e)}
        source_file.save(update_fields=['status', 'import_report'])
        raise

    return result
