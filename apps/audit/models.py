from django.db import models
from django.conf import settings


class AuditLog(models.Model):
    ACTION_UPDATE = 'update'
    ACTION_MERGE = 'merge'
    ACTION_DELETE = 'delete'
    ACTION_IMPORT = 'import'
    ACTION_VERIFY = 'verify'
    ACTION_REASSIGN = 'reassign'

    ACTION_CHOICES = [
        (ACTION_UPDATE, 'Modification'),
        (ACTION_MERGE, 'Fusion'),
        (ACTION_DELETE, 'Suppression'),
        (ACTION_IMPORT, 'Import'),
        (ACTION_VERIFY, 'Vérification'),
        (ACTION_REASSIGN, 'Réattribution'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name='audit_logs',
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    model_name = models.CharField(max_length=50)
    object_id = models.PositiveIntegerField()
    object_repr = models.CharField(max_length=200, blank=True)
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Log d\'audit'
        verbose_name_plural = 'Logs d\'audit'
        ordering = ['-timestamp']

    def __str__(self):
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {self.user} — {self.get_action_display()} {self.model_name}#{self.object_id}"
