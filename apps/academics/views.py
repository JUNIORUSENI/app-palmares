from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.db.models import Count
from django.core.paginator import Paginator

from apps.accounts.mixins import editor_required
from apps.audit.utils import log_action
from .models import Student, GradeRecord, AcademicYear, ClassRoom

PAGE_SIZE = 30


@login_required
def student_list(request):
    query = request.GET.get('q', '').strip()
    page = request.GET.get('page', 1)

    students = Student.objects.annotate(grade_count=Count('grades'))

    if query:
        students = students.filter(full_name__icontains=query)

    students = students.order_by('full_name')

    paginator = Paginator(students, PAGE_SIZE)
    page_obj = paginator.get_page(page)

    ctx = {
        'page_obj': page_obj,
        'query': query,
        'total_count': paginator.count,
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
    # Graphique : ordre chronologique (la plus ancienne à gauche), sans null
    grades_chart = (
        student.grades
        .select_related('academic_year')
        .filter(percentage__isnull=False)
        .order_by('academic_year__label')
    )
    return render(request, 'academics/student_detail.html', {
        'student': student,
        'grades': grades,
        'grades_chart': grades_chart,
    })


@editor_required
def student_merge(request, pk):
    student = get_object_or_404(Student, pk=pk)

    if request.method == 'POST':
        target_id = request.POST.get('target_id')
        target = get_object_or_404(Student, pk=target_id)

        # Réattribuer tous les résultats vers la cible
        GradeRecord.objects.filter(student=student).update(student=target)
        log_action(request.user, 'merge', 'Student', student.pk,
                   old_value={'full_name': student.full_name},
                   new_value={'merged_into': target.full_name})
        student.delete()
        messages.success(request, f"'{student.full_name}' fusionné avec '{target.full_name}'.")
        return redirect('academics:student_detail', pk=target.pk)

    # Suggestions de doublons par similarité de nom
    candidates = (
        Student.objects
        .filter(full_name__icontains=student.full_name.split()[0])
        .exclude(pk=student.pk)[:10]
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
        new_pct = request.POST.get('percentage', '').strip()
        if new_pct == '':
            value = None
        else:
            try:
                from decimal import Decimal, InvalidOperation
                value = Decimal(new_pct)
                if not (Decimal('0') <= value <= Decimal('100')):
                    raise ValueError('hors limites')
            except (ValueError, InvalidOperation):
                return render(request, 'academics/partials/grade_cell.html', {
                    'grade': grade, 'error': 'Valeur invalide (0–100)'
                })

        old_value = float(grade.percentage)
        grade.percentage = value
        grade.is_verified = False
        grade.verified_by = None
        grade.verified_at = None
        grade.save(update_fields=['percentage', 'is_verified', 'verified_by', 'verified_at'])

        log_action(request.user, 'update', 'GradeRecord', grade.pk,
                   old_value={'percentage': old_value},
                   new_value={'percentage': float(value)})

        return render(request, 'academics/partials/grade_cell.html', {'grade': grade})

    # GET → retourner le formulaire d'édition inline
    return render(request, 'academics/partials/grade_edit_form.html', {'grade': grade})


@editor_required
def grade_cell(request, pk):
    """Retourne la cellule en mode lecture (pour annuler une édition inline)."""
    grade = get_object_or_404(GradeRecord, pk=pk)
    return render(request, 'academics/partials/grade_cell.html', {'grade': grade})


@editor_required
@require_http_methods(['GET', 'POST'])
def student_name_edit(request, pk):
    student = get_object_or_404(Student, pk=pk)

    if request.method == 'POST':
        new_name = request.POST.get('full_name', '').strip()
        if not new_name:
            return render(request, 'academics/partials/student_name_display.html', {
                'student': student, 'error': 'Le nom ne peut pas être vide.'
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
