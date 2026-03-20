from django.urls import path
from . import views

app_name = 'imports'

urlpatterns = [
    path('', views.import_list, name='import_list'),
    path('upload/', views.import_upload, name='import_upload'),
    path('<int:pk>/dry-run/', views.import_dry_run, name='import_dry_run'),
    path('<int:pk>/dry-run/status/', views.import_dry_run_status, name='import_dry_run_status'),
    path('<int:pk>/confirm/', views.import_confirm, name='import_confirm'),
    path('<int:pk>/progress/', views.import_progress, name='import_progress'),
    path('<int:pk>/status/', views.import_status, name='import_status'),
    path('<int:pk>/rollback/', views.import_rollback, name='import_rollback'),
]
