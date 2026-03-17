from django.contrib import admin
from .models import SourceFile


@admin.register(SourceFile)
class SourceFileAdmin(admin.ModelAdmin):
    list_display = ('original_filename', 'academic_year', 'status', 'imported_by', 'imported_at', 'total_rows', 'imported_rows')
    list_filter = ('status', 'academic_year')
    readonly_fields = ('imported_at', 'dry_run_report', 'import_report', 'total_rows', 'imported_rows', 'error_rows')
