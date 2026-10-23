from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Count
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.accounts.mixins import editor_required
from apps.audit.utils import log_action
from apps.core.pagination import paginate
from apps.core.text import name_key, normalize_label, safe_json
from apps.imports.excel import parse_percentage
from .models import Student, GradeRecord, AcademicYear, ClassRoom
from .services import MergeError, class_grades, grade_summary, merge_students, ranked_grades, year_class_tree

PAGE_SIZE = 30          # liste des élèves
GRADES_PAGE_SIZE = 15   # résultats d'un élève
RESULTS_PAGE_SIZE = 50  # résultats d'une classe
NAME_MAX_LENGTH = Student._meta.get_field('full_name').max_length


@login_required
def student_list(request):
    query = request.GET.get('q', '').strip()

    students = Student.objects.annotate(grade_count=Count('grades'))

    if query:
        # Recherche insensible à la casse, aux accents, aux espaces et aux tirets
        students = students.filter(name_key__contains=name_key(query))

    students = students.order_by('full_name')

    page_obj = paginate(request, students, PAGE_SIZE)

    ctx = {
        'page_obj': page_obj,
        'query': query,
        'total_count': page_obj.paginator.count,
    }

    if request.htmx:
        return render(request, 'academics/partials/student_rows.html', ctx)
    return render(request, 'academics/student_list.html', ctx)


@login_required
def student_detail(request, pk):
    student = get_object_or_404(Student, pk=pk)
    # Table : année la plus récente en premier
    grades = (
        student.grades
        .select_related('classroom', 'academic_year', 'verified_by')
        .order_by('-academic_year__label')
    )
    return render(request, 'academics/student_detail.html', {
        'student': student,
        'grades': paginate(request, grades, GRADES_PAGE_SIZE),
    })


@editor_required
@require_http_methods(['GET', 'POST'])
def student_merge(request, pk):
    student = get_object_or_404(Student, pk=pk)

    if request.method == 'POST':
        try:
            target = Student.objects.get(pk=int(request.POST.get('target_id', '')))
        except (ValueError, Student.DoesNotExist):
            messages.error(request, "Élève cible introuvable.")
            return redirect('academics:student_merge', pk=pk)

        source_pk, source_name = student.pk, student.full_name
        grade_count = student.grades.count()
        try:
            result = merge_students(student, target)
        except MergeError as exc:
            messages.error(request, str(exc))
            return redirect('academics:student_merge', pk=pk)

        log_action(request.user, 'merge', 'Student', source_pk,
                   old_value={'full_name': source_name, 'grade_count': grade_count},
                   new_value={'merged_into': target.full_name, 'target_id': target.pk, **result},
                   object_repr=source_name)
        messages.success(request, f"'{source_name}' fusionné avec '{target.full_name}'.")
        if result['conflicts']:
            messages.warning(
                request,
                f"{len(result['conflicts'])} résultat(s) existaient déjà pour la même classe et la même "
                "année : un seul a été conservé (détail dans le journal d'audit)."
            )
        return redirect('academics:student_detail', pk=target.pk)

    # Suggestions de doublons par similarité de nom (pg_trgm), les plus proches d'abord
    candidates = (
        Student.objects
        .exclude(pk=student.pk)
        .annotate(similarity=TrigramSimilarity('full_name', student.full_name))
        .filter(similarity__gt=0.3)
        .annotate(grade_count=Count('grades'))
        .order_by('-similarity', 'full_name')[:10]
    )
    return render(request, 'academics/student_merge.html', {
        'student': student,
        'candidates': candidates,
    })


@editor_required
@require_http_methods(['POST'])
def grade_verify(request, pk):
    grade = get_object_or_404(GradeRecord, pk=pk)
    grade.is_verified = not grade.is_verified
    grade.verified_by = request.user if grade.is_verified else None
    grade.verified_at = timezone.now() if grade.is_verified else None
    grade.save(update_fields=['is_verified', 'verified_by', 'verified_at'])

    log_action(request.user, 'verify', 'GradeRecord', grade.pk,
               new_value={'is_verified': grade.is_verified})

    return render(request, 'academics/partials/verify_badge.html', {'grade': grade})


@editor_required
@require_http_methods(['GET', 'POST'])
def grade_edit_inline(request, pk):
    grade = get_object_or_404(GradeRecord, pk=pk)

    if request.method == 'POST':
        value, error = parse_percentage(request.POST.get('percentage', '').strip())
        if error:
            return render(request, 'academics/partials/grade_cell.html', {
                'grade': grade, 'error': 'Valeur invalide (0–100)'
            })

        old_value = float(grade.percentage) if grade.percentage is not None else None
        grade.percentage = value
        grade.is_verified = False
        grade.verified_by = None
        grade.verified_at = None
        grade.save(update_fields=['percentage', 'is_verified', 'verified_by', 'verified_at'])

        log_action(request.user, 'update', 'GradeRecord', grade.pk,
                   old_value={'percentage': old_value},
                   new_value={'percentage': float(value) if value is not None else None})

        return render(request, 'academics/partials/grade_cell.html', {'grade': grade})

    # GET → retourner le formulaire d'édition inline
    return render(request, 'academics/partials/grade_edit_form.html', {'grade': grade})


@editor_required
def grade_cell(request, pk):
    """Retourne la cellule en mode lecture (pour annuler une édition inline)."""
    grade = get_object_or_404(GradeRecord, pk=pk)
    return render(request, 'academics/partials/grade_cell.html', {'grade': grade})


@editor_required
@require_http_methods(['DELETE'])
def grade_delete(request, pk):
    grade = get_object_or_404(
        GradeRecord.objects.select_related('student', 'classroom', 'academic_year'),
        pk=pk,
    )
    old_value = {
        'student': grade.student.full_name,
        'classroom': str(grade.classroom),
        'academic_year': str(grade.academic_year),
        'percentage': float(grade.percentage) if grade.percentage is not None else None,
    }
    log_action(request.user, 'delete', 'GradeRecord', grade.pk,
               old_value=old_value, object_repr=str(grade))
    grade.delete()
    return render(request, 'academics/partials/grade_deleted_row.html')


@editor_required
@require_http_methods(['GET', 'POST'])
def student_delete(request, pk):
    student = get_object_or_404(Student, pk=pk)
    grade_count = student.grades.count()

    if request.method == 'POST':
        old_value = {
            'full_name': student.full_name,
            'grade_count': grade_count,
        }
        log_action(request.user, 'delete', 'Student', student.pk,
                   old_value=old_value, object_repr=student.full_name)
        student.delete()  # CASCADE supprime aussi les GradeRecords
        messages.success(request, f"L'élève « {student.full_name} » et ses {grade_count} résultat(s) ont été supprimés.")
        return redirect('academics:student_list')

    return render(request, 'academics/student_delete_confirm.html', {
        'student': student,
        'grade_count': grade_count,
    })


@editor_required
@require_http_methods(['GET', 'POST'])
def student_name_edit(request, pk):
    student = get_object_or_404(Student, pk=pk)

    if request.method == 'POST':
        # Même normalisation que Student.save() : majuscules, espaces nettoyés
        new_name = normalize_label(request.POST.get('full_name', ''))
        if not new_name or len(new_name) > NAME_MAX_LENGTH:
            return render(request, 'academics/partials/student_name_display.html', {
                'student': student,
                'error': 'Le nom ne peut pas être vide.' if not new_name
                         else f'Le nom est trop long (max {NAME_MAX_LENGTH} caractères).',
            })

        old_name = student.full_name
        student.full_name = new_name
        student.save(update_fields=['full_name'])

        log_action(request.user, 'update', 'Student', student.pk,
                   old_value={'full_name': old_name},
                   new_value={'full_name': new_name})

        return render(request, 'academics/partials/student_name_display.html', {'student': student})

    return render(request, 'academics/partials/student_name_edit_form.html', {'student': student})


@editor_required
def student_name_display(request, pk):
    """Retourne le nom en mode lecture (pour annuler l'édition)."""
    student = get_object_or_404(Student, pk=pk)
    return render(request, 'academics/partials/student_name_display.html', {'student': student})


@editor_required
def results_index(request):
    """Page Résultats : sélecteur année → section → classe."""
    tree = year_class_tree()
    years_list = [{'id': pk, 'label': v['label']} for pk, v in tree.items()]
    return render(request, 'academics/results_index.html', {
        'years_list_json': safe_json(years_list),
        'data_json': safe_json(tree),
    })


@editor_required
def results_table(request, year_pk, class_pk):
    """Partial HTMX : tableau des résultats d'une classe pour une année."""
    year = get_object_or_404(AcademicYear, pk=year_pk)
    classroom = get_object_or_404(ClassRoom, pk=class_pk)

    grades = class_grades(year, classroom)
    return render(request, 'academics/partials/results_table.html', {
        'year': year,
        'classroom': classroom,
        'rows': paginate(request, ranked_grades(grades), RESULTS_PAGE_SIZE),
        'stats': grade_summary(grades),
    })
