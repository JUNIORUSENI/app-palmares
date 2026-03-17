from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.home, name='home'),
    path('search/', views.global_search, name='search'),
    path('year/<int:year_pk>/', views.year_dashboard, name='year_dashboard'),
    path('year/<int:year_pk>/class/<int:class_pk>/', views.class_palmares, name='class_palmares'),
    path('api/student/<int:student_pk>/chart/', views.student_chart_data, name='student_chart_data'),
    path('statistiques/', views.admin_stats, name='admin_stats'),
]
