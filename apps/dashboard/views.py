import json
from django.shortcuts import render, get_object_or_404, redirect


def _safe_json(data):
    """json.dumps avec échappement des caractères HTML dangereux (<, >, &).
    Indispensable pour injecter du JSON directement dans une balise <script>.
    """
    return (
        json.dumps(data)
        .replace('<', r'\u003c')
        .replace('>', r'\u003e')
        .replace('&', r'\u0026')
    )

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Avg, Count, Q, Sum
from django.contrib.postgres.search import TrigramSimilarity

from apps.academics.models import AcademicYear, ClassRoom, GradeRecord, Student
from apps.accounts.mixins import reader_redirect, admin_required


@login_required
@reader_redirect
def home(request):
    from apps.imports.models import SourceFile

    years = AcademicYear.objects.annotate(
        student_count=Count('grades__student', distinct=True),
        grade_count=Count('grades'),
    ).order_by('-label')

    stats = {
        'total_students': Student.objects.count(),
        'total_grades': GradeRecord.objects.count(),
        'total_files': SourceFile.objects.count(),
    }

    recent_files = SourceFile.objects.select_related('academic_year').order_by('-imported_at')[:5]

    return render(request, 'dashboard/home.html', {
        'years': years,
        'stats': stats,
        'recent_files': recent_files,
    })


@login_required
def global_search(request):
    query = request.GET.get('q', '').strip()
    results = []
    if len(query) >= 2:
        results = (
            Student.objects
            .annotate(similarity=TrigramSimilarity('full_name', query))
            .filter(similarity__gt=0.15)
            .order_by('-similarity')[:20]
        )
    return render(request, 'dashboard/partials/search_results.html', {
        'query': query, 'results': results,
    })


@login_required
@reader_redirect
def year_dashboard(request, year_pk):
    year = get_object_or_404(AcademicYear, pk=year_pk)

    stats = GradeRecord.objects.filter(academic_year=year).aggregate(
        avg_pct=Avg('percentage'),
        total=Count('id'),
        passed=Count('id', filter=Q(percentage__gte=50)),
    )

    classes = (
        ClassRoom.objects
        .filter(grades__academic_year=year)
        .annotate(
            avg_pct=Avg('grades__percentage'),
            student_count=Count('grades__student', distinct=True),
            verified_count=Count('grades__id', filter=Q(grades__is_verified=True)),
        )
        .order_by('section', 'name')
    )

    pass_rate = round(stats['passed'] / stats['total'] * 100, 1) if stats['total'] else 0

    return render(request, 'dashboard/year_dashboard.html', {
        'year': year,
        'stats': stats,
        'pass_rate': pass_rate,
        'classes': classes,
    })


@login_required
def student_chart_data(request, student_pk):
    """Retourne les données Chart.js pour l'évolution d'un élève."""
    student = get_object_or_404(Student, pk=student_pk)
    grades = (
        student.grades
        .select_related('academic_year')
        .order_by('academic_year__label')
    )
    data = {
        'labels': [g.academic_year.label for g in grades],
        'data': [float(g.percentage) for g in grades],
    }
    return JsonResponse(data)


@login_required
@reader_redirect
def class_palmares(request, year_pk, class_pk):
    year = get_object_or_404(AcademicYear, pk=year_pk)
    classroom = get_object_or_404(ClassRoom, pk=class_pk)

    grades = (
        GradeRecord.objects
        .filter(academic_year=year, classroom=classroom)
        .select_related('student', 'verified_by')
        .order_by('-percentage')
    )

    return render(request, 'dashboard/class_palmares.html', {
        'year': year,
        'classroom': classroom,
        'grades': grades,
        'total': grades.count(),
        'passed': grades.filter(percentage__gte=50).count(),
    })


@login_required
@admin_required
def admin_stats(request):
    from apps.imports.models import SourceFile
    from apps.audit.models import AuditLog

    # ── KPIs globaux ──────────────────────────────────────────────
    total_students = Student.objects.count()
    total_grades = GradeRecord.objects.count()
    graded = GradeRecord.objects.filter(percentage__isnull=False)
    graded_count = graded.count()
    passed_count = graded.filter(percentage__gte=50).count()
    verified_count = GradeRecord.objects.filter(is_verified=True).count()
    pass_rate = round(passed_count / graded_count * 100, 1) if graded_count else 0
    verify_rate = round(verified_count / total_grades * 100, 1) if total_grades else 0
    kpis = {
        'total_students': total_students,
        'total_grades': total_grades,
        'pass_rate': pass_rate,
        'verify_rate': verify_rate,
        'passed_count': passed_count,
        'verified_count': verified_count,
    }

    # ── Évolution par année ───────────────────────────────────────
    year_stats = list(
        AcademicYear.objects
        .annotate(
            total=Count('grades', filter=Q(grades__percentage__isnull=False)),
            passed=Count('grades', filter=Q(grades__percentage__gte=50)),
            avg_pct=Avg('grades__percentage'),
        )
        .filter(total__gt=0)
        .order_by('label')
    )
    year_trend = {
        'labels': [y.label for y in year_stats],
        'pass_rates': [round(y.passed / y.total * 100, 1) if y.total else 0 for y in year_stats],
        'avg_pcts': [round(float(y.avg_pct), 1) if y.avg_pct else 0 for y in year_stats],
    }

    # ── Distribution des notes (histogramme) ─────────────────────
    dist_labels, dist_counts = [], []
    for lo in range(0, 100, 10):
        if lo == 90:
            cnt = graded.filter(percentage__gte=90).count()
            lbl = '90–100'
        else:
            cnt = graded.filter(percentage__gte=lo, percentage__lt=lo + 10).count()
            lbl = f'{lo}–{lo + 9}'
        dist_labels.append(lbl)
        dist_counts.append(cnt)

    # ── Réussite par section ──────────────────────────────────────
    section_data = list(
        GradeRecord.objects
        .filter(percentage__isnull=False)
        .values('classroom__section')
        .annotate(
            total=Count('id'),
            passed=Count('id', filter=Q(percentage__gte=50)),
            avg_pct=Avg('percentage'),
        )
        .order_by('classroom__section')
    )
    for s in section_data:
        s['pass_rate'] = round(s['passed'] / s['total'] * 100, 1) if s['total'] else 0
        s['avg_pct'] = round(float(s['avg_pct']), 1) if s['avg_pct'] else 0

    # ── Top 10 classes par moyenne ────────────────────────────────
    top_classes = list(
        ClassRoom.objects
        .annotate(
            avg_pct=Avg('grades__percentage'),
            total=Count('grades', filter=Q(grades__percentage__isnull=False)),
        )
        .filter(total__gte=3)
        .order_by('-avg_pct')[:10]
    )

    # ── Taux de vérification par année ────────────────────────────
    verify_stats = list(
        AcademicYear.objects
        .annotate(
            total=Count('grades'),
            verified=Count('grades', filter=Q(grades__is_verified=True)),
        )
        .filter(total__gt=0)
        .order_by('label')
    )

    # ── Top 10 élèves par moyenne ─────────────────────────────────
    top_students = list(
        Student.objects
        .annotate(
            avg_pct=Avg('grades__percentage'),
            grade_count=Count('grades'),
        )
        .filter(grade_count__gte=1, avg_pct__isnull=False)
        .order_by('-avg_pct')[:10]
    )

    # ── Élèves à échecs répétés ───────────────────────────────────
    repeated_failures = list(
        Student.objects
        .annotate(
            fail_count=Count('grades', filter=Q(
                grades__percentage__lt=50,
                grades__percentage__isnull=False,
            )),
            grade_count=Count('grades'),
        )
        .filter(fail_count__gte=2)
        .order_by('-fail_count')[:10]
    )

    # ── Activité des utilisateurs (AuditLog) ─────────────────────
    role_map = {'admin': 'Administrateur', 'editor': 'Éditeur', 'reader': 'Lecteur'}
    user_activity = list(
        AuditLog.objects
        .filter(user__isnull=False)
        .values('user__id', 'user__username', 'user__role')
        .annotate(total=Count('id'))
        .order_by('-total')[:8]
    )
    max_activity = max((u['total'] for u in user_activity), default=1)
    for ua in user_activity:
        ua['role_display'] = role_map.get(ua.get('user__role') or '', '—')
        ua['pct'] = round(ua['total'] / max_activity * 100)

    # ── Statistiques d'imports ────────────────────────────────────
    import_stats = {
        'total': SourceFile.objects.count(),
        'done': SourceFile.objects.filter(status=SourceFile.STATUS_DONE).count(),
        'error': SourceFile.objects.filter(status=SourceFile.STATUS_ERROR).count(),
        'pending': SourceFile.objects.filter(
            status__in=[SourceFile.STATUS_PENDING, SourceFile.STATUS_PROCESSING]
        ).count(),
        'total_rows': SourceFile.objects.aggregate(s=Sum('imported_rows'))['s'] or 0,
    }
    recent_imports = (
        SourceFile.objects
        .select_related('academic_year', 'imported_by')
        .order_by('-imported_at')[:6]
    )

    return render(request, 'dashboard/admin_stats.html', {
        'kpis': kpis,
        'year_trend_json': _safe_json(year_trend),
        'distribution_json': _safe_json({'labels': dist_labels, 'counts': dist_counts}),
        'section_stats_json': _safe_json({
            'labels': [s['classroom__section'] or 'Sans section' for s in section_data],
            'pass_rates': [s['pass_rate'] for s in section_data],
            'avg_pcts': [s['avg_pct'] for s in section_data],
        }),
        'top_classes_json': _safe_json({
            'labels': [c.name for c in top_classes],
            'values': [round(float(c.avg_pct), 1) if c.avg_pct else 0 for c in top_classes],
        }),
        'verify_trend_json': _safe_json({
            'labels': [y.label for y in verify_stats],
            'verified': [y.verified for y in verify_stats],
            'unverified': [y.total - y.verified for y in verify_stats],
        }),
        'top_students': top_students,
        'repeated_failures': repeated_failures,
        'user_activity': user_activity,
        'import_stats': import_stats,
        'recent_imports': recent_imports,
    })
