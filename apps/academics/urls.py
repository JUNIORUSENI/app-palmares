from django.urls import path
from . import views

app_name = 'academics'

urlpatterns = [
    path('students/', views.student_list, name='student_list'),
    path('students/<int:pk>/', views.student_detail, name='student_detail'),
    path('students/<int:pk>/merge/', views.student_merge, name='student_merge'),
    path('grades/<int:pk>/verify/', views.grade_verify, name='grade_verify'),
    path('grades/<int:pk>/edit/', views.grade_edit_inline, name='grade_edit_inline'),
    path('grades/<int:pk>/cell/', views.grade_cell, name='grade_cell'),
    path('grades/<int:pk>/delete/', views.grade_delete, name='grade_delete'),
    path('students/<int:pk>/delete/', views.student_delete, name='student_delete'),
    path('students/<int:pk>/name/edit/', views.student_name_edit, name='student_name_edit'),
    path('students/<int:pk>/name/', views.student_name_display, name='student_name_display'),
    path('resultats/', views.results_index, name='results_index'),
    path('resultats/<int:year_pk>/<int:class_pk>/', views.results_table, name='results_table'),
]
