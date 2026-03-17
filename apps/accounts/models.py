from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    ROLE_ADMIN = 'admin'
    ROLE_EDITOR = 'editor'
    ROLE_READER = 'reader'

    ROLE_CHOICES = [
        (ROLE_ADMIN, 'Administrateur'),
        (ROLE_EDITOR, 'Éditeur'),
        (ROLE_READER, 'Lecteur'),
    ]

    role = models.CharField(
        max_length=10,
        choices=ROLE_CHOICES,
        default=ROLE_READER,
    )

    class Meta:
        verbose_name = 'Utilisateur'
        verbose_name_plural = 'Utilisateurs'

    @property
    def is_admin(self):
        return self.role == self.ROLE_ADMIN

    @property
    def is_editor(self):
        return self.role in (self.ROLE_ADMIN, self.ROLE_EDITOR)

    @property
    def is_reader(self):
        return True  # Tous les rôles ont accès en lecture

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"
