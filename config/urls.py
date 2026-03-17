from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('', include('apps.dashboard.urls')),
    path('academics/', include('apps.academics.urls')),
    path('imports/', include('apps.imports.urls')),
    path('exports/', include('apps.exports.urls', namespace='exports')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
