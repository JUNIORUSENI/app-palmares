from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.text import name_key, normalize_label, normalize_year_label


class AcademicYear(models.Model):
    label = models.CharField(max_length=20, unique=True)  # ex: "2024-2025"

    class Meta:
        verbose_name = 'Année scolaire'
        verbose_name_plural = 'Années scolaires'
        ordering = ['-label']

    def __str__(self):
        return self.label

    def clean(self):
        # Appelé avant la vérification d'unicité des formulaires : « 2024 - 2025 » devient « 2024-2025 »
        self.label = normalize_year_label(self.label)

    def save(self, *args, **kwargs):
        self.label = normalize_year_label(self.label)
        super().save(*args, **kwargs)


class ClassRoom(models.Model):
    name = models.CharField(max_length=100)       # ex: "7 EB A"
    section = models.CharField(max_length=100)    # ex: "Secondaire"

    class Meta:
        verbose_name = 'Classe'
        verbose_name_plural = 'Classes'
        unique_together = ('name', 'section')
        ordering = ['section', 'name']

    def __str__(self):
        return f"{self.name} ({self.section})"

    def clean(self):
        self.name = normalize_label(self.name)
        self.section = normalize_label(self.section)

    def save(self, *args, **kwargs):
        # Majuscules et espaces nettoyés : « Classe de seconde » et « Classe de Seconde » ne font plus qu'une classe
        self.name = normalize_label(self.name)
        self.section = normalize_label(self.section)
        super().save(*args, **kwargs)


class Student(models.Model):
    full_name = models.CharField(max_length=200, db_index=True)
    # Clé de comparaison (sans accents, espaces ni casse) : évite les doublons à l'import.
    # Recalculée automatiquement à chaque save().
    # db_default : l'ancienne version du code (sans ce champ) peut toujours insérer des élèves, ce qui
    # permet un retour en arrière sans restaurer la base.
    name_key = models.CharField(max_length=200, blank=True, default='', db_default='', db_index=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Élève'
        verbose_name_plural = 'Élèves'
        ordering = ['full_name']
        indexes = [
            # Recherche floue (pg_trgm) et filtres icontains de la barre de recherche
            GinIndex(fields=['full_name'], name='student_fullname_trgm', opclasses=['gin_trgm_ops']),
        ]

    def __str__(self):
        return self.full_name

    def clean(self):
        self.full_name = normalize_label(self.full_name)

    def save(self, *args, **kwargs):
        # Tous les noms sont stockés en MAJUSCULES, espaces nettoyés : une seule graphie par élève
        self.full_name = normalize_label(self.full_name)
        self.name_key = name_key(self.full_name)
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'full_name' in update_fields:
            kwargs['update_fields'] = {*update_fields, 'name_key'}
        super().save(*args, **kwargs)


class GradeRecord(models.Model):
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='grades'
    )
    classroom = models.ForeignKey(
        ClassRoom, on_delete=models.CASCADE, related_name='grades'
    )
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.CASCADE, related_name='grades'
    )
    percentage = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('100'))],
    )

    # Vérification croisée
    is_verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='verified_grades',
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    # Fichier qui a CRÉÉ cette note (les mises à jour d'un import ultérieur
    # sont tracées dans imports.ImportChange)
    source_file = models.ForeignKey(
        'imports.SourceFile',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='grade_records',
    )

    class Meta:
        verbose_name = 'Résultat'
        verbose_name_plural = 'Résultats'
        unique_together = ('student', 'classroom', 'academic_year')
        ordering = ['-academic_year__label', 'classroom', '-percentage']
        indexes = [
            # Palmarès d'une classe pour une année : requête la plus fréquente
            models.Index(fields=['academic_year', 'classroom'], name='grade_year_class_idx'),
        ]

    def __str__(self):
        return f"{self.student} — {self.classroom} — {self.academic_year}: {self.percentage}%"
