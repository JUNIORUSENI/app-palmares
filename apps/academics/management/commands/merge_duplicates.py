"""Uniformise les noms (majuscules, espaces) et fusionne les doublons d'élèves, de classes et d'années.

    python manage.py merge_duplicates            # simulation : liste ce qui serait modifié
    python manage.py merge_duplicates --apply    # applique

Les anciens imports comparaient les noms à la lettre près : « MOÏSE », « MOISE » et « Moïse »
créaient trois élèves, « Classe de seconde » et « Classe de Seconde » deux classes. Les imports et
formulaires actuels normalisent tout, mais les doublons déjà présents en base doivent être réunis une fois.

Ordre : clés manquantes, élèves, classes, années, puis mise en majuscules des noms restants.
"""
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db.models import Count

from apps.academics.models import AcademicYear, ClassRoom, GradeRecord, Student
from apps.academics.services import merge_classrooms, merge_students, merge_years
from apps.audit.utils import log_action
from apps.core.text import normalize_label, normalize_year_label


class Command(BaseCommand):
    help = "Met les noms en majuscules et fusionne les élèves, classes et années en double."

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help="Applique (sinon simple simulation).")

    def handle(self, *args, **options):
        self.apply = options['apply']
        self.merged = 0
        self.groups = 0
        self.overlaps = 0
        self.renamed = 0
        self.merged_away = set()      # (modèle, pk) des fiches absorbées, pour la simulation

        self.fix_missing_keys()
        self.merge_students_by_key()
        self.merge_by_normalized_name(
            ClassRoom, 'classe',
            key=lambda c: (normalize_label(c.name), normalize_label(c.section)),
            describe=lambda c: f"{c.name} / {c.section}",
            overlap_key=lambda g: (g.student_id, g.academic_year_id), fk='classroom',
            merge=merge_classrooms,
        )
        self.merge_by_normalized_name(
            AcademicYear, 'année',
            key=lambda y: normalize_year_label(y.label),
            describe=lambda y: y.label,
            overlap_key=lambda g: (g.student_id, g.classroom_id), fk='academic_year',
            merge=merge_years,
        )
        self.normalize_remaining_names()
        self.summary()

    # ── Étapes ───────────────────────────────────────────────────

    def fix_missing_keys(self):
        """Élèves créés par une ancienne version du code (après un retour en arrière) : clé à recalculer."""
        stale = Student.objects.filter(name_key='').exclude(full_name='')
        count = stale.count()
        if not count:
            return
        self.stdout.write(f"{count} élève(s) sans clé de comparaison" + (" : recalcul." if self.apply else " (recalculés avec --apply)."))
        if self.apply:
            for student in stale.iterator():
                student.save(update_fields=['full_name'])

    def merge_students_by_key(self):
        keys = (
            Student.objects.exclude(name_key='')
            .values('name_key').annotate(n=Count('id')).filter(n__gt=1)
            .values_list('name_key', flat=True)
        )
        for key in keys.order_by('name_key'):
            students = list(
                Student.objects.filter(name_key=key).annotate(grade_count=Count('grades'))
                .order_by('-grade_count', 'pk')
            )
            target, others = students[0], students[1:]
            self.groups += 1
            self.stdout.write(f"ÉLÈVE {key}  ->  garde « {target.full_name} » ({target.grade_count} résultat(s))")
            for other in others:
                taken = set(GradeRecord.objects.filter(student=target).values_list('classroom_id', 'academic_year_id'))
                clash = GradeRecord.objects.filter(student=other).values_list('classroom_id', 'academic_year_id')
                self.absorb(
                    Student, other, target, label=other.full_name,
                    conflicts=sum(1 for pair in clash if pair in taken),
                    merge=merge_students,
                    old={'full_name': other.full_name, 'grade_count': other.grade_count},
                    describe_target=target.full_name,
                )

    def merge_by_normalized_name(self, model, noun, key, describe, overlap_key, fk, merge):
        buckets = defaultdict(list)
        for obj in model.objects.annotate(grade_count=Count('grades')).order_by('-grade_count', 'pk'):
            buckets[key(obj)].append(obj)
        for objs in buckets.values():
            if len(objs) < 2:
                continue
            target, others = objs[0], objs[1:]
            self.groups += 1
            self.stdout.write(f"{noun.upper()} {describe(target)}  ->  garde cette fiche ({target.grade_count} résultat(s))")
            for other in others:
                taken = {overlap_key(g) for g in GradeRecord.objects.filter(**{fk: target})}
                clash = sum(1 for g in GradeRecord.objects.filter(**{fk: other}) if overlap_key(g) in taken)
                self.absorb(
                    model, other, target, label=describe(other), conflicts=clash, merge=merge,
                    old={'name': describe(other), 'grade_count': other.grade_count},
                    describe_target=describe(target),
                )
            if self.apply:
                target.save()          # remet le nom de la fiche conservée en majuscules

    def absorb(self, model, other, target, label, conflicts, merge, old, describe_target):
        self.overlaps += conflicts
        note = f", {conflicts} résultat(s) en double (un seul gardé)" if conflicts else ""
        self.stdout.write(f"      + « {label} » ({old['grade_count']} résultat(s)){note}")
        self.merged_away.add((model, other.pk))
        if self.apply:
            pk = other.pk
            result = merge(other, target)
            log_action(None, 'merge', model.__name__, pk, old_value=old,
                       new_value={'merged_into': describe_target, 'target_id': target.pk,
                                  'by': 'merge_duplicates', **result},
                       object_repr=label)
            self.merged += 1

    def normalize_remaining_names(self):
        """Met en majuscules les noms qui ne sont pas (encore) normalisés."""
        todo = []
        for student in Student.objects.iterator():
            if (Student, student.pk) not in self.merged_away and student.full_name != normalize_label(student.full_name):
                todo.append(student)
        for cls in ClassRoom.objects.all():
            if (ClassRoom, cls.pk) not in self.merged_away and (
                cls.name != normalize_label(cls.name) or cls.section != normalize_label(cls.section)
            ):
                todo.append(cls)
        for year in AcademicYear.objects.all():
            if (AcademicYear, year.pk) not in self.merged_away and year.label != normalize_year_label(year.label):
                todo.append(year)
        self.renamed = len(todo)
        if self.apply:
            for obj in todo:
                obj.save()             # save() applique la normalisation

    def summary(self):
        if not (self.groups or self.renamed):
            self.stdout.write(self.style.SUCCESS("Rien à faire : noms uniformes, aucun doublon."))
            return
        if self.apply:
            self.stdout.write(self.style.SUCCESS(
                f"{self.merged} fiche(s) fusionnée(s) ({self.groups} groupe(s)), {self.overlaps} résultat(s) en double écarté(s), "
                f"{self.renamed} nom(s) mis en majuscules."
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f"SIMULATION : {self.groups} groupe(s) de doublons ({self.overlaps} résultat(s) en double), "
                f"{self.renamed} nom(s) à mettre en majuscules. Relancez avec --apply pour appliquer."
            ))
