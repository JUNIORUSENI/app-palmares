from django.db import models
from django.conf import settings


class AcademicYear(models.Model):
    label = models.CharField(max_length=20, unique=True)  # ex: "2024-2025"

    class Meta:
        verbose_name = 'Année scolaire'
        verbose_name_plural = 'Années scolaires'
        ordering = ['-label']

    def __str__(self):
        return self.label


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


class Student(models.Model):
    full_name = models.CharField(max_length=200, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Élève'
        verbose_name_plural = 'Élèves'
        ordering = ['full_name']

    def __str__(self):
        return self.full_name


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
    percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    # Vérification croisée
    is_verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='verified_grades',
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    # Traçabilité de la source
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

    def __str__(self):
        return f"{self.student} — {self.classroom} — {self.academic_year}: {self.percentage}%"
