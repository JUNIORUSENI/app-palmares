from django.core.paginator import Paginator


def paginate(request, items, per_page, param='page'):
    """Découpe `items` (QuerySet ou liste, déjà ordonné) et retourne la page demandée.

    Un numéro de page invalide ou hors limites ne provoque pas d'erreur : on retombe sur la
    première ou la dernière page. `page.page_numbers` contient les numéros à afficher
    (None = « … »), utilisés par templates/components/pagination.html.
    """
    paginator = Paginator(items, per_page)
    page = paginator.get_page(request.GET.get(param))
    page.page_numbers = [
        None if number == paginator.ELLIPSIS else number
        for number in paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)
    ]
    return page
