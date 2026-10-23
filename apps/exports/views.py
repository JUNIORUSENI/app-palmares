import csv
import re

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string

from apps.academics.models import AcademicYear, ClassRoom, GradeRecord, Student
from apps.academics.services import class_grades, grade_summary, ranked_grades, year_class_tree
from apps.core.text import csv_safe, name_key, safe_json


def _safe_filename(name):
    """Remplace tout caractère non alphanumérique/tiret/point par _ pour Content-Disposition."""
    return re.sub(r'[^\w\-.]', '_', name)


def _status_columns(grade):
    """(pourcentage affiché, statut) d'un résultat."""
    if grade.percentage is None:
        return '—', 'Non noté'
    return str(grade.percentage).replace('.', ','), ('Admis' if grade.percentage >= 50 else 'Ajourné')


def _pdf_response(template, context, filename):
    html = render_to_string(template, context)
    try:
        from weasyprint import HTML
    except ImportError:
        return HttpResponse("WeasyPrint non installé.", status=500)
    response = HttpResponse(HTML(string=html).write_pdf(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{_safe_filename(filename)}"'
    return response


@login_required
def export_index(request):
    tree = year_class_tree()
    years_list = [{'id': pk, 'label': v['label']} for pk, v in tree.items()]
    return render(request, 'exports/export_index.html', {
        'years_list': years_list,
        'export_data_json': safe_json(tree),
    })


@login_required
def export_csv_palmares(request, year_pk, class_pk):
    year = get_object_or_404(AcademicYear, pk=year_pk)
    classroom = get_object_or_404(ClassRoom, pk=class_pk)

    filename = _safe_filename(f"palmares_{classroom.name}_{year.label}.csv")
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write('\ufeff')  # BOM pour Excel

    writer = csv.writer(response, delimiter=';')
    writer.writerow(['Rang', 'Nom complet', 'Classe', 'Section', 'Année', 'Pourcentage', 'Statut', 'Vérifié'])

    for rank, grade in ranked_grades(class_grades(year, classroom)):
        pct_str, statut = _status_columns(grade)
        writer.writerow([
            rank if rank is not None else '—',
            csv_safe(grade.student.full_name),
            csv_safe(classroom.name),
            csv_safe(classroom.section),
            year.label,
            pct_str,
            statut,
            'Oui' if grade.is_verified else 'Non',
        ])

    return response


@login_required
def export_csv_students(request):
    query = request.GET.get('q', '').strip()
    year_id = request.GET.get('year', '').strip()

    grades = GradeRecord.objects.select_related('student', 'classroom', 'academic_year').all()

    if query:
        grades = grades.filter(student__name_key__contains=name_key(query))
    if year_id.isdigit():  # identifiant invalide : on ignore le filtre
        grades = grades.filter(academic_year_id=int(year_id))

    grades = grades.order_by('student__full_name', '-academic_year__label')

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="resultats.csv"'
    response.write('\ufeff')

    writer = csv.writer(response, delimiter=';')
    writer.writerow(['Nom complet', 'Classe', 'Section', 'Année', 'Pourcentage', 'Statut', 'Vérifié'])

    for grade in grades.iterator(chunk_size=2000):
        pct_str, statut = _status_columns(grade)
        writer.writerow([
            csv_safe(grade.student.full_name),
            csv_safe(grade.classroom.name),
            csv_safe(grade.classroom.section),
            grade.academic_year.label,
            pct_str,
            statut,
            'Oui' if grade.is_verified else 'Non',
        ])

    return response


@login_required
def export_pdf_palmares(request, year_pk, class_pk):
    year = get_object_or_404(AcademicYear, pk=year_pk)
    classroom = get_object_or_404(ClassRoom, pk=class_pk)

    grades = class_grades(year, classroom)
    return _pdf_response(
        'exports/palmares_pdf.html',
        {'year': year, 'classroom': classroom, 'rows': ranked_grades(grades), 'stats': grade_summary(grades)},
        f"palmares_{classroom.name}_{year.label}.pdf",
    )


@login_required
def export_pdf_student(request, student_pk):
    student = get_object_or_404(Student, pk=student_pk)
    grades = (
        student.grades
        .select_related('classroom', 'academic_year')
        .order_by('-academic_year__label')
    )
    return _pdf_response(
        'exports/student_pdf.html',
        {'student': student, 'grades': grades},
        f"releve_{student.full_name}.pdf",
    )
