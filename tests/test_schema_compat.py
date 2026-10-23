import pytest
from django.db import connection

from apps.academics.models import Student
from apps.imports.models import SourceFile

pytestmark = pytest.mark.django_db


def test_previous_code_can_still_write_after_the_migration():
    """L'ancienne version du code ignore name_key et updated_at : ses INSERT ne doivent pas échouer.
    C'est ce qui permet un retour en arrière du code SANS restaurer la base."""
    with connection.cursor() as cursor:
        cursor.execute("INSERT INTO academics_student (full_name, created_at, updated_at) VALUES ('CREE PAR ANCIEN CODE', now(), now())")
        cursor.execute(
            "INSERT INTO imports_sourcefile (file, original_filename, imported_at, status, dry_run_report, import_report,"
            " total_rows, imported_rows, error_rows) VALUES ('imports/x.xlsx', 'x.xlsx', now(), 'pending', '{}', '{}', 0, 0, 0)"
        )
    assert Student.objects.get().name_key == ''
    assert SourceFile.objects.get().updated_at is not None
