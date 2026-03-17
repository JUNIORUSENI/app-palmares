import csv
import json
import re
from django.shortcuts import get_object_or_404, render
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.template.loader import render_to_string

from apps.academics.models import AcademicYear, ClassRoom, GradeRecord, Student


def _safe_json(data):
    """json.dumps avec échappement HTML pour usage sécurisé dans <script>."""
    return (
        json.dumps(data)
        .replace('<', r'\u003c')
        .replace('>', r'\u003e')
        .replace('&', r'\u0026')
    )


def _safe_filename(name):
    """Remplace tout caractère non alphanumérique/tiret/point par _ pour Content-Disposition."""
    return re.sub(r'[^\w\-.]', '_', name)


@login_required
def export_index(request):
    years = AcademicYear.objects.order_by('-label')

    # Construire une structure année → sections → classes
    # { year_id: { label, sections: { section_label: [ {id, name} ] } } }
    data = {}
    for year in years:
        classrooms = (
            ClassRoom.objects
            .filter(grades__academic_year=year)
            .distinct()
            .order_by('section', 'name')
        )
        sections = {}
        for cls in classrooms:
            sec = cls.section or 'Sans section'
            sections.setdefault(sec, []).append({'id': cls.pk, 'name': cls.name})

        if sections:
            data[year.pk] = {
                'label': year.label,
                'sections': sections,
            }

    years_list = [{'id': pk, 'label': v['label']} for pk, v in data.items()]
    return render(request, 'exports/export_index.html', {
        'years_list': years_list,
        'export_data_json': _safe_json(data),
    })


@login_required
def export_csv_palmares(request, year_pk, class_pk):
    year = get_object_or_404(AcademicYear, pk=year_pk)
    classroom = get_object_or_404(ClassRoom, pk=class_pk)

    grades = (
        GradeRecord.objects
        .filter(academic_year=year, classroom=classroom)
        .select_related('student', 'verified_by')
        .order_by('-percentage')
    )

    filename = _safe_filename(f"palmares_{classroom.name}_{year.label}.csv")
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write('\ufeff')  # BOM pour Excel

    writer = csv.writer(response, delimiter=';')
    writer.writerow(['Rang', 'Nom complet', 'Classe', 'Section', 'Année', 'Pourcentage', 'Statut', 'Vérifié'])

    for rank, grade in enumerate(grades, start=1):
        if grade.percentage is None:
            pct_str, statut = '—', 'Non noté'
        else:
            pct_str = str(grade.percentage).replace('.', ',')
            statut = 'Admis' if grade.percentage >= 50 else 'Ajourné'
        writer.writerow([
            rank,
            grade.student.full_name,
            classroom.name,
            classroom.section,
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
        grades = grades.filter(student__full_name__icontains=query)
    if year_id:
        try:
            grades = grades.filter(academic_year_id=int(year_id))
        except (ValueError, TypeError):
            pass  # year_id invalide : ignorer le filtre

    grades = grades.order_by('student__full_name', '-academic_year__label')

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="resultats.csv"'
    response.write('\ufeff')

    writer = csv.writer(response, delimiter=';')
    writer.writerow(['Nom complet', 'Classe', 'Section', 'Année', 'Pourcentage', 'Statut', 'Vérifié'])

    for grade in grades:
        if grade.percentage is None:
            pct_str, statut = '—', 'Non noté'
        else:
            pct_str = str(grade.percentage).replace('.', ',')
            statut = 'Admis' if grade.percentage >= 50 else 'Ajourné'
        writer.writerow([
            grade.student.full_name,
            grade.classroom.name,
            grade.classroom.section,
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

    grades = (
        GradeRecord.objects
        .filter(academic_year=year, classroom=classroom)
        .select_related('student')
        .order_by('-percentage')
    )

    html = render_to_string('exports/palmares_pdf.html', {
        'year': year,
        'classroom': classroom,
        'grades': grades,
        'total': grades.count(),
        'passed': grades.filter(percentage__gte=50).count(),
    })

    try:
        from weasyprint import HTML
        pdf = HTML(string=html).write_pdf()
        filename = _safe_filename(f"palmares_{classroom.name}_{year.label}.pdf")
        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    except ImportError:
        return HttpResponse("WeasyPrint non installé.", status=500)


@login_required
def export_pdf_student(request, student_pk):
    student = get_object_or_404(Student, pk=student_pk)
    grades = (
        student.grades
        .select_related('classroom', 'academic_year')
        .order_by('-academic_year__label')
    )

    html = render_to_string('exports/student_pdf.html', {
        'student': student,
        'grades': grades,
    })

    try:
        from weasyprint import HTML
        pdf = HTML(string=html).write_pdf()
        filename = _safe_filename(f"releve_{student.full_name}.pdf")
        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    except ImportError:
        return HttpResponse("WeasyPrint non installé.", status=500)
