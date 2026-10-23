"""Logique métier des résultats : classement, statistiques, fusions, arbre année → classes."""
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, F, Q

from .models import AcademicYear, ClassRoom, GradeRecord, Student

PASS_MARK = Decimal('50')


def class_grades(year, classroom):
    """Résultats d'une classe, du meilleur au moins bon. Les élèves sans note sont placés
    à la fin (PostgreSQL met sinon les NULL en premier avec un tri décroissant)."""
    return (
        GradeRecord.objects
        .filter(academic_year=year, classroom=classroom)
        .select_related('student', 'verified_by')
        .order_by(F('percentage').desc(nulls_last=True), 'student__full_name')
    )


def ranked_grades(grades):
    """Retourne [(rang, grade)]. Les ex æquo partagent le même rang (1, 2, 2, 4) ;
    les élèves sans note n'ont pas de rang (None)."""
    rows = []
    rank = None
    previous = None
    for position, grade in enumerate(grades, start=1):
        if grade.percentage is None:
            rows.append((None, grade))
            continue
        if grade.percentage != previous:
            rank = position
            previous = grade.percentage
        rows.append((rank, grade))
    return rows


def grade_summary(grades):
    """Statistiques d'un ensemble de résultats. Le taux de réussite est calculé sur les
    élèves NOTÉS uniquement, de la même façon partout dans l'application."""
    stats = grades.aggregate(
        total=Count('id'),
        graded=Count('percentage'),
        passed=Count('id', filter=Q(percentage__gte=PASS_MARK)),
        unverified=Count('id', filter=Q(is_verified=False)),
    )
    graded = stats['graded']
    stats['ungraded'] = stats['total'] - graded
    stats['failed'] = graded - stats['passed']
    stats['pass_rate'] = round(stats['passed'] / graded * 100, 1) if graded else None
    return stats


def year_class_tree():
    """{id_année: {'label': ..., 'sections': {section: [{'id': ..., 'name': ...}]}}}
    Une seule requête (utilisée par les sélecteurs année → section → classe)."""
    rows = (
        GradeRecord.objects
        .order_by('-academic_year__label', 'classroom__section', 'classroom__name')
        .values_list(
            'academic_year_id', 'academic_year__label',
            'classroom_id', 'classroom__name', 'classroom__section',
        )
        .distinct()
    )
    tree = {}
    for year_id, year_label, class_id, class_name, section in rows:
        year = tree.setdefault(year_id, {'label': year_label, 'sections': {}})
        year['sections'].setdefault(section or 'Sans section', []).append(
            {'id': class_id, 'name': class_name}
        )
    return tree


# ── Fusions ──────────────────────────────────────────────────────

class MergeError(Exception):
    """Fusion impossible (message affichable à l'utilisateur)."""


def _absorb(kept, dropped):
    """Deux résultats occupent la même place (même élève, classe et année) : on n'en garde qu'un.

    On garde celui de la cible (`kept`), sauf s'il n'a pas de note, ou si seul l'autre est vérifié :
    dans ce cas on lui prend sa note. `dropped` est supprimé. Retourne un résumé pour le journal.
    """
    take_dropped = dropped.percentage is not None and (
        kept.percentage is None or (dropped.is_verified and not kept.is_verified)
    )
    summary = {
        'student': str(dropped.student),
        'classroom': str(dropped.classroom),
        'academic_year': str(dropped.academic_year),
        'kept': str(dropped.percentage if take_dropped else kept.percentage),
        'dropped': str(kept.percentage if take_dropped else dropped.percentage),
    }
    if take_dropped:
        kept.percentage = dropped.percentage
        kept.is_verified = dropped.is_verified
        kept.verified_by = dropped.verified_by
        kept.verified_at = dropped.verified_at
        kept.save(update_fields=['percentage', 'is_verified', 'verified_by', 'verified_at'])
    dropped.delete()
    return summary


def _merge_grades(source_grades, target_grades, key, field, target):
    """Transfère les résultats de `source_grades` vers `target` (en modifiant `field`).
    `target_grades` : résultats déjà présents chez la cible, indexés par `key(grade)`."""
    moved = 0
    conflicts = []
    for grade in source_grades:
        existing = target_grades.get(key(grade))
        if existing is None:
            setattr(grade, field, target)
            grade.save(update_fields=[field])
            moved += 1
        else:
            conflicts.append(_absorb(existing, grade))
    return {'moved': moved, 'conflicts': conflicts}


def _lock_pair(model, source, target):
    """Verrouille les deux lignes (ordre stable : pas de blocage entre deux fusions croisées)."""
    if source.pk == target.pk:
        raise MergeError("Impossible de fusionner un élément avec lui-même.")
    locked = model.objects.select_for_update().filter(pk__in=[source.pk, target.pk]).order_by('pk')
    if len(list(locked)) != 2:
        raise MergeError("L'un des deux éléments n'existe plus.")


def _grades(**filters):
    return (
        GradeRecord.objects
        .select_for_update(of=('self',))
        .select_related('student', 'classroom', 'academic_year', 'verified_by')
        .filter(**filters)
    )


@transaction.atomic
def merge_students(source, target):
    """Transfère les résultats de `source` vers `target` puis supprime `source`."""
    if source.pk == target.pk:
        raise MergeError("Impossible de fusionner un élève avec lui-même.")
    _lock_pair(Student, source, target)
    result = _merge_grades(
        _grades(student=source),
        {(g.classroom_id, g.academic_year_id): g for g in _grades(student=target)},
        key=lambda g: (g.classroom_id, g.academic_year_id), field='student', target=target,
    )
    source.delete()
    return result


@transaction.atomic
def merge_classrooms(source, target):
    """Réunit deux classes en double : les résultats de `source` passent dans `target`."""
    _lock_pair(ClassRoom, source, target)
    result = _merge_grades(
        _grades(classroom=source),
        {(g.student_id, g.academic_year_id): g for g in _grades(classroom=target)},
        key=lambda g: (g.student_id, g.academic_year_id), field='classroom', target=target,
    )
    source.delete()
    return result


@transaction.atomic
def merge_years(source, target):
    """Réunit deux années en double : résultats et fichiers importés passent dans `target`."""
    from apps.imports.models import SourceFile

    _lock_pair(AcademicYear, source, target)
    result = _merge_grades(
        _grades(academic_year=source),
        {(g.student_id, g.classroom_id): g for g in _grades(academic_year=target)},
        key=lambda g: (g.student_id, g.classroom_id), field='academic_year', target=target,
    )
    SourceFile.objects.filter(academic_year=source).update(academic_year=target)
    source.delete()
    return result
