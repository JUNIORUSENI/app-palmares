from django.contrib import admin
from .models import AcademicYear, ClassRoom, Student, GradeRecord


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ('label',)
    search_fields = ('label',)


@admin.register(ClassRoom)
class ClassRoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'section')
    list_filter = ('section',)
    search_fields = ('name', 'section')


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'created_at')
    search_fields = ('full_name',)


@admin.register(GradeRecord)
class GradeRecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'classroom', 'academic_year', 'percentage', 'is_verified')
    list_filter = ('academic_year', 'classroom__section', 'is_verified')
    search_fields = ('student__full_name',)
    raw_id_fields = ('student', 'classroom', 'academic_year', 'verified_by')
