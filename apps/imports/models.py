from django.db import models
from django.conf import settings


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

    file = models.FileField(upload_to='imports/%Y/%m/')
    original_filename = models.CharField(max_length=255)
    academic_year = models.ForeignKey(
        'academics.AcademicYear',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='source_files',
    )
    imported_at = models.DateTimeField(auto_now_add=True)
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
