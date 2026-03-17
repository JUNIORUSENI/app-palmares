from django.urls import path
from . import views

app_name = 'exports'

urlpatterns = [
    path('', views.export_index, name='export_index'),
    path('csv/palmares/<int:year_pk>/<int:class_pk>/', views.export_csv_palmares, name='csv_palmares'),
    path('csv/students/', views.export_csv_students, name='csv_students'),
    path('pdf/palmares/<int:year_pk>/<int:class_pk>/', views.export_pdf_palmares, name='pdf_palmares'),
    path('pdf/student/<int:student_pk>/', views.export_pdf_student, name='pdf_student'),
]
