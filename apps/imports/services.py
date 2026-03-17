import pandas as pd
from decimal import Decimal, InvalidOperation

EXPECTED_COLUMNS = {'Nom complet', 'Pourcentage', 'Classe', 'Section', 'Année scolaire'}


def _load_dataframe(file_path):
    df = pd.read_excel(file_path, dtype=str)
    df.columns = df.columns.str.strip()
    df = df.dropna(how='all')
    return df


def _validate_row(row, row_num):
    errors = []

    full_name = str(row.get('Nom complet', '') or '').strip()
    if not full_name:
        errors.append(f"Ligne {row_num} : Nom complet vide")

    percentage_raw = str(row.get('Pourcentage', '') or '').strip().replace(',', '.')
    percentage = None
    if percentage_raw:
        try:
            percentage = Decimal(percentage_raw)
            if not (Decimal('0') <= percentage <= Decimal('100')):
                errors.append(f"Ligne {row_num} : Pourcentage hors limites ({percentage})")
                percentage = None
        except InvalidOperation:
            errors.append(f"Ligne {row_num} : Pourcentage invalide ({percentage_raw!r})")

    classroom_name = str(row.get('Classe', '') or '').strip()
    if not classroom_name:
        errors.append(f"Ligne {row_num} : Classe vide")

    section = str(row.get('Section', '') or '').strip()
    year_label = str(row.get('Année scolaire', '') or '').strip()

    cleaned = {
        'full_name': full_name,
        'percentage': percentage,
        'classroom_name': classroom_name,
        'section': section,
        'year_label': year_label,
    }
    return cleaned, errors


def dry_run(file_path):
    """Analyse le fichier et retourne un rapport sans rien écrire en base."""
    try:
        df = _load_dataframe(file_path)
    except Exception:
        return {
            'status': 'error',
            'message': "Impossible de lire le fichier. Vérifiez qu'il s'agit bien d'un fichier Excel (.xlsx ou .xls) valide.",
            'total_rows': 0, 'valid_rows': 0, 'error_rows': 0,
            'errors': [], 'missing_columns': [],
        }

    missing_cols = EXPECTED_COLUMNS - set(df.columns)
    if missing_cols:
        return {
            'status': 'error',
            'message': f"Colonnes manquantes : {', '.join(missing_cols)}",
            'total_rows': len(df), 'valid_rows': 0, 'error_rows': len(df),
            'errors': [f"Colonne manquante : {col}" for col in missing_cols],
            'missing_columns': list(missing_cols),
        }

    all_errors = []
    valid_count = 0

    for i, row in enumerate(df.to_dict('records'), start=2):
        _, row_errors = _validate_row(row, i)
        if row_errors:
            all_errors.extend(row_errors)
        else:
            valid_count += 1

    return {
        'status': 'ok' if not all_errors else 'warning',
        'total_rows': len(df),
        'valid_rows': valid_count,
        'error_rows': len(df) - valid_count,
        'errors': all_errors[:100],
        'missing_columns': [],
    }


def do_import(file_path, source_file_obj, task=None):
    """
    Importe les données du fichier en base de données.
    `task` est la tâche Celery (optionnel) pour mettre à jour la progression.
    """
    from apps.academics.models import AcademicYear, ClassRoom, Student, GradeRecord

    df = _load_dataframe(file_path)
    total = len(df)
    imported = 0
    skipped = 0
    last_year = None

    for i, row in enumerate(df.to_dict('records'), start=2):
        cleaned, errors = _validate_row(row, i)
        if errors:
            skipped += 1
            continue

        year, _ = AcademicYear.objects.get_or_create(label=cleaned['year_label'])
        last_year = year
        classroom, _ = ClassRoom.objects.get_or_create(
            name=cleaned['classroom_name'],
            defaults={'section': cleaned['section']},
        )
        student, _ = Student.objects.get_or_create(full_name=cleaned['full_name'])

        GradeRecord.objects.update_or_create(
            student=student,
            classroom=classroom,
            academic_year=year,
            defaults={
                'percentage': cleaned['percentage'],
                'source_file': source_file_obj,
            },
        )
        imported += 1

        if task and i % 50 == 0:
            task.update_state(
                state='PROGRESS',
                meta={'current': imported, 'total': total},
            )

    # Rattache l'année scolaire au SourceFile
    if last_year and not source_file_obj.academic_year_id:
        source_file_obj.academic_year = last_year
        source_file_obj.save(update_fields=['academic_year'])

    return {'total': total, 'imported': imported, 'skipped': skipped}
