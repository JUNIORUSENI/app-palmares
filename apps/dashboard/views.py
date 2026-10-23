from django.contrib.auth.decorators import login_required
from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Avg, Count, Q, Sum
from django.shortcuts import render, get_object_or_404

from apps.academics.models import AcademicYear, ClassRoom, GradeRecord, Student
from apps.academics.services import class_grades, grade_summary, ranked_grades
from apps.accounts.mixins import reader_redirect, admin_required
from apps.core.pagination import paginate

YEARS_PAGE_SIZE = 15
CLASSES_PAGE_SIZE = 25
PALMARES_PAGE_SIZE = 50
AUDIT_PAGE_SIZE = 50


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
        'years': paginate(request, years, YEARS_PAGE_SIZE),
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

    year_grades = GradeRecord.objects.filter(academic_year=year)
    stats = grade_summary(year_grades)
    stats['avg_pct'] = year_grades.aggregate(avg=Avg('percentage'))['avg']

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

    return render(request, 'dashboard/year_dashboard.html', {
        'year': year,
        'stats': stats,
        'pass_rate': stats['pass_rate'] or 0,
        'classes': paginate(request, classes, CLASSES_PAGE_SIZE),
    })


@login_required
@reader_redirect
def class_palmares(request, year_pk, class_pk):
    year = get_object_or_404(AcademicYear, pk=year_pk)
    classroom = get_object_or_404(ClassRoom, pk=class_pk)

    grades = class_grades(year, classroom)
    return render(request, 'dashboard/class_palmares.html', {
        'year': year,
        'classroom': classroom,
        'rows': paginate(request, ranked_grades(grades), PALMARES_PAGE_SIZE),
        'stats': grade_summary(grades),
    })


@login_required
@admin_required
def admin_stats(request):
    from apps.imports.models import SourceFile
    from apps.audit.models import AuditLog

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
        'user_activity': user_activity,
        'import_stats': import_stats,
        'recent_imports': recent_imports,
    })


@login_required
@admin_required
def audit_log(request):
    from apps.audit.models import AuditLog
    from apps.accounts.models import User

    qs = AuditLog.objects.select_related('user').all()

    # Filtres
    action = request.GET.get('action', '')
    user_id = request.GET.get('user', '')
    model = request.GET.get('model', '')

    if action:
        qs = qs.filter(action=action)
    if user_id.isdigit():  # un identifiant non numérique provoquerait une erreur 500
        qs = qs.filter(user_id=int(user_id))
    if model:
        qs = qs.filter(model_name=model)

    page = paginate(request, qs, AUDIT_PAGE_SIZE)

    users = User.objects.filter(audit_logs__isnull=False).distinct().order_by('username')
    actions = AuditLog.ACTION_CHOICES
    models_list = (
        AuditLog.objects.values_list('model_name', flat=True)
        .distinct()
        .order_by('model_name')
    )

    return render(request, 'dashboard/audit_log.html', {
        'page': page,
        'users': users,
        'actions': actions,
        'models_list': models_list,
        'current_action': action,
        'current_user': user_id,
        'current_model': model,
    })
