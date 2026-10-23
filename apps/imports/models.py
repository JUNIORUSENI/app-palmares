import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import models
from django.db.models.functions import Now
from django.utils import timezone

# Au-delà de ce délai, un fichier « en cours » est considéré comme bloqué
# (la limite dure des tâches Celery est de 6 minutes).
STALE_AFTER = timedelta(minutes=10)


def import_upload_path(instance, filename):
    """Nom de stockage imprévisible : le nom d'origine reste dans original_filename."""
    extension = Path(filename).suffix.lower()
    return f"imports/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{extension}"


class SourceFile(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_DONE = 'done'
    STATUS_ERROR = 'error'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'En attente'),
        (STATUS_PROCESSING, 'En cours de traitement'),
        (STATUS_DONE, 'Terminé'),
        (STATUS_ERROR, 'Erreur'),
    ]

    file = models.FileField(upload_to=import_upload_path)
    original_filename = models.CharField(max_length=255)
    academic_year = models.ForeignKey(
        'academics.AcademicYear',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='source_files',
    )
    imported_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name='imported_files',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)

    # Rapport du dry-run et du traitement (JSON)
    dry_run_report = models.JSONField(default=dict, blank=True)
    import_report = models.JSONField(default=dict, blank=True)

    # Lot d'import (plusieurs fichiers uploadés en une fois)
    batch_id = models.UUIDField(null=True, blank=True, db_index=True)

    # Stats rapides
    total_rows = models.PositiveIntegerField(default=0)
    imported_rows = models.PositiveIntegerField(default=0)
    error_rows = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Fichier source'
        verbose_name_plural = 'Fichiers sources'
        ordering = ['-imported_at']

    def __str__(self):
        return f"{self.original_filename} — {self.academic_year} ({self.get_status_display()})"

    def mark(self, status, **fields):
        """Change le statut et rafraîchit updated_at (nécessaire à la détection des blocages)."""
        self.status = status
        for name, value in fields.items():
            setattr(self, name, value)
        self.save(update_fields=['status', 'updated_at', *fields])

    @property
    def is_analyzed(self):
        """L'analyse (dry-run) est terminée et exploitable."""
        report = self.dry_run_report or {}
        return bool(report) and report.get('status') in ('ok', 'warning')

    @property
    def is_stale(self):
        """Fichier resté « en cours » (ou jamais pris en charge) trop longtemps :
        le worker a probablement été arrêté ou la tâche perdue."""
        waiting = self.status == self.STATUS_PROCESSING or (
            self.status == self.STATUS_PENDING and not self.dry_run_report
        )
        return waiting and timezone.now() - self.updated_at > STALE_AFTER


class ImportChange(models.Model):
    """Note existante modifiée par un import : permet de la restaurer si l'import est annulé."""
    source_file = models.ForeignKey(SourceFile, on_delete=models.CASCADE, related_name='changes')
    grade = models.ForeignKey('academics.GradeRecord', on_delete=models.CASCADE, related_name='import_changes')
    old_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    new_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = "Modification d'import"
        verbose_name_plural = "Modifications d'import"

    def __str__(self):
        return f"{self.source_file_id}: {self.old_percentage} → {self.new_percentage}"
