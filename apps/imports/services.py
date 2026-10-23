"""ETL des palmarès : analyse à blanc (dry-run), import et annulation."""
import logging
from collections import Counter
from dataclasses import dataclass, field

from django.db import connection, transaction

from apps.academics.models import AcademicYear, ClassRoom, GradeRecord, Student
from apps.core.text import name_key, normalize_label

from .excel import ImportFileError, read_workbook, validate_row
from .models import ImportChange

logger = logging.getLogger(__name__)

MAX_REPORTED_ERRORS = 100
MAX_REPORTED_DETAILS = 20
# Verrou PostgreSQL : un seul import à la fois (deux imports simultanés pourraient créer
# le même élève en double ou violer l'unicité d'un résultat).
IMPORT_LOCK_ID = 734_001


@dataclass
class Prepared:
    """Contenu d'un fichier après lecture et validation, sans accès à la base."""
    rows: list = field(default_factory=list)       # [(emplacement, valeurs nettoyées)]
    total: int = 0
    invalid: int = 0
    duplicates: int = 0
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def prepare(file_path):
    """Lit le fichier et valide chaque ligne. Lève ImportFileError si le fichier est inutilisable."""
    sheets, ignored = read_workbook(file_path)
    prepared = Prepared()
    for name, missing in ignored:
        prepared.warnings.append(f"Feuille « {name} » ignorée : colonnes manquantes ({', '.join(missing)}).")

    multiple = len(sheets) > 1
    seen = {}
    for sheet in sheets:
        if sheet.fraction_scaled:
            prepared.warnings.append(
                f"Feuille « {sheet.name} » : tous les pourcentages sont compris entre 0 et 1, "
                "ils ont été interprétés comme des fractions (0,75 = 75 %)."
            )
        for number, cells in sheet.rows:
            prepared.total += 1
            location = f"Feuille « {sheet.name} », ligne {number}" if multiple else f"Ligne {number}"
            cleaned, errors = validate_row(cells, sheet.fraction_scaled)
            if errors:
                prepared.invalid += 1
                prepared.errors.extend(f"{location} : {error}" for error in errors)
                continue
            key = (name_key(cleaned['full_name']), cleaned['classroom_name'],
                   cleaned['section'], cleaned['year_label'])
            if key in seen:
                prepared.duplicates += 1
                prepared.errors.append(
                    f"{location} : doublon de {seen[key].lower()} (même élève, même classe, même année)"
                )
                continue
            seen[key] = location
            prepared.rows.append((location, cleaned))
    return prepared


class _Lookup:
    """Retrouve (ou crée) années, classes et élèves en tolérant les variantes de graphie."""

    def __init__(self, create):
        self.create = create
        self.years = {}
        for year in AcademicYear.objects.order_by('pk'):
            self.years.setdefault(year.label, year)
        self.classrooms = {}
        for classroom in ClassRoom.objects.order_by('pk'):
            self.classrooms.setdefault((normalize_label(classroom.name), normalize_label(classroom.section)), classroom)
        self.students = {}

    def year(self, label):
        year = self.years.get(label)
        if year is None and self.create:
            year = self.years[label] = AcademicYear.objects.create(label=label)
        return year

    def classroom(self, name, section):
        classroom = self.classrooms.get((name, section))
        if classroom is None and self.create:
            classroom = self.classrooms[(name, section)] = ClassRoom.objects.create(name=name, section=section)
        return classroom

    def student(self, full_name):
        key = name_key(full_name)
        if key not in self.students:
            student = Student.objects.filter(name_key=key).order_by('pk').first()
            if student is None and self.create:
                student = Student.objects.create(full_name=full_name)
            self.students[key] = student
        return self.students[key]


def _existing_grade(lookup, cleaned):
    year = lookup.year(cleaned['year_label'])
    classroom = lookup.classroom(cleaned['classroom_name'], cleaned['section'])
    student = lookup.student(cleaned['full_name'])
    existing = None
    if year and classroom and student:
        existing = GradeRecord.objects.filter(
            student=student, classroom=classroom, academic_year=year
        ).first()
    return year, classroom, student, existing


def _decide(existing, new_percentage):
    """'create' | 'update' | 'unchanged' | 'blocked'.

    - une note déjà vérifiée par un humain n'est jamais écrasée ;
    - une cellule vide n'efface pas une note existante.
    """
    if existing is None:
        return 'create'
    if new_percentage is None or existing.percentage == new_percentage:
        return 'unchanged'
    if existing.is_verified:
        return 'blocked'
    return 'update'


def _blocked_message(location, cleaned, existing):
    return (
        f"{location} : {cleaned['full_name']} ({cleaned['classroom_name']}, {cleaned['year_label']}) "
        f"est déjà vérifié à {existing.percentage} %, la valeur du fichier ({cleaned['percentage']} %) est ignorée."
    )


def _error_report(message, missing=()):
    return {
        'status': 'error', 'message': message,
        'total_rows': 0, 'valid_rows': 0, 'error_rows': 0,
        'errors': [f"Colonne manquante : {column}" for column in missing],
        'missing_columns': list(missing), 'warnings': [],
    }


def dry_run(file_path):
    """Analyse le fichier et retourne un rapport sans rien écrire en base."""
    try:
        prepared = prepare(file_path)
    except ImportFileError as exc:
        return _error_report(str(exc), exc.missing_columns)
    except Exception:
        logger.exception("Échec de l'analyse du fichier %s", file_path)
        return _error_report(
            "Impossible de lire le fichier. Vérifiez qu'il s'agit bien d'un fichier Excel (.xlsx ou .xls) valide."
        )

    lookup = _Lookup(create=False)
    counts = Counter()
    blocked = []
    for location, cleaned in prepared.rows:
        *_, existing = _existing_grade(lookup, cleaned)
        action = _decide(existing, cleaned['percentage'])
        counts[action] += 1
        if action == 'blocked' and len(blocked) < MAX_REPORTED_DETAILS:
            blocked.append(_blocked_message(location, cleaned, existing))

    error_rows = prepared.invalid + prepared.duplicates
    return {
        'status': 'warning' if (prepared.errors or prepared.warnings or counts['blocked']) else 'ok',
        'total_rows': prepared.total,
        'valid_rows': len(prepared.rows),
        'error_rows': error_rows,
        'errors': prepared.errors[:MAX_REPORTED_ERRORS],
        'warnings': prepared.warnings,
        'missing_columns': [],
        'to_create': counts['create'],
        'to_update': counts['update'],
        'unchanged': counts['unchanged'],
        'blocked': counts['blocked'],
        'blocked_details': blocked,
    }


def do_import(file_path, source_file, task=None):
    """Importe le fichier dans une transaction atomique (tout ou rien).

    - nouvelle note   : créée et rattachée au fichier (source_file) ;
    - note existante  : mise à jour et tracée (ImportChange) pour pouvoir être restaurée ;
    - note vérifiée   : jamais écrasée (comptée dans « blocked »).
    """
    prepared = prepare(file_path)
    counts = Counter()
    blocked = []
    changes = []
    year_usage = Counter()

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [IMPORT_LOCK_ID])

        lookup = _Lookup(create=True)
        for index, (location, cleaned) in enumerate(prepared.rows, start=1):
            year, classroom, student, existing = _existing_grade(lookup, cleaned)
            new_percentage = cleaned['percentage']
            action = _decide(existing, new_percentage)
            counts[action] += 1
            year_usage[year.pk] += 1

            if action == 'create':
                GradeRecord.objects.create(
                    student=student, classroom=classroom, academic_year=year,
                    percentage=new_percentage, source_file=source_file,
                )
            elif action == 'update':
                changes.append(ImportChange(
                    source_file=source_file, grade=existing,
                    old_percentage=existing.percentage, new_percentage=new_percentage,
                ))
                existing.percentage = new_percentage
                existing.save(update_fields=['percentage'])
            elif action == 'blocked' and len(blocked) < MAX_REPORTED_DETAILS:
                blocked.append(_blocked_message(location, cleaned, existing))

            if task and index % 50 == 0:
                task.update_state(state='PROGRESS', meta={'current': index, 'total': len(prepared.rows)})

        ImportChange.objects.bulk_create(changes, batch_size=1000)

        # Année principale du fichier (la plus fréquente)
        if year_usage and not source_file.academic_year_id:
            source_file.academic_year_id = year_usage.most_common(1)[0][0]
            source_file.save(update_fields=['academic_year'])

    return {
        'total': prepared.total,
        'imported': counts['create'] + counts['update'],
        'created': counts['create'],
        'updated': counts['update'],
        'unchanged': counts['unchanged'],
        'blocked': counts['blocked'],
        'blocked_details': blocked,
        'skipped': prepared.invalid + prepared.duplicates,
        'warnings': prepared.warnings,
    }


def rollback_import(source_file):
    """Annule un import : supprime les notes CRÉÉES par ce fichier et restaure les valeurs
    qu'il avait modifiées.

    Une note modifiée n'est restaurée que si elle n'a pas été retouchée depuis (même valeur
    que celle de l'import, non vérifiée) : on ne perd jamais le travail d'un éditeur.
    Retourne {'deleted': n, 'restored': n, 'kept': n}.
    """
    with transaction.atomic():
        restored = kept = 0
        for change in source_file.changes.select_related('grade'):
            grade = change.grade
            if grade.percentage == change.new_percentage and not grade.is_verified:
                grade.percentage = change.old_percentage
                grade.save(update_fields=['percentage'])
                restored += 1
            else:
                kept += 1
        created = source_file.grade_records.all()
        deleted = created.count()
        created.delete()
        source_file.delete()
    return {'deleted': deleted, 'restored': restored, 'kept': kept}
