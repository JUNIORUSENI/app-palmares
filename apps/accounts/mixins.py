from functools import wraps
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def editor_required(view_func):
    """Réservé aux éditeurs et admins. Redirige les lecteurs vers la liste des élèves."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not request.user.is_editor:
            return redirect('academics:student_list')
        return view_func(request, *args, **kwargs)
    return wrapper


def admin_required(view_func):
    """Réservé aux admins uniquement. Redirige les autres vers la liste des élèves."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not request.user.is_admin:
            return redirect('academics:student_list')
        return view_func(request, *args, **kwargs)
    return wrapper


def reader_redirect(view_func):
    """Redirige les lecteurs vers la liste des élèves (pour les vues réservées éditeurs/admins)."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not request.user.is_editor:
            return redirect('academics:student_list')
        return view_func(request, *args, **kwargs)
    return wrapper
