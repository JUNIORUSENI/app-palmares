from decimal import Decimal

import pytest

from apps.core.text import collapse_spaces, csv_safe, name_key, normalize_label, normalize_year_label, safe_json
from apps.imports.excel import (
    Cell, ImportFileError, parse_percentage, read_workbook, validate_row,
)


# ── Normalisation des libellés ───────────────────────────────────

@pytest.mark.parametrize('a, b', [
    ('Jean  Dupont', 'JEAN DUPONT'),
    ('Ndayé Mukendi', 'NDAYE MUKENDI'),
    ("N’Daye-Mukendi", "n'daye mukendi"),
    ('  Élodie   Kabasele ', 'ELODIE KABASELE'),
])
def test_name_key_ignores_case_accents_spaces_and_punctuation(a, b):
    assert name_key(a) == name_key(b)


def test_name_key_keeps_different_people_apart():
    assert name_key('Jean Dupont') != name_key('Jean Dupond')


@pytest.mark.parametrize('raw, expected', [
    ('2024-2025', '2024-2025'),
    ('2024 - 2025', '2024-2025'),
    ('2024/2025', '2024-2025'),
    ('2024 – 2025', '2024-2025'),
    ('  annee speciale ', 'ANNEE SPECIALE'),
])
def test_year_label_normalization(raw, expected):
    assert normalize_year_label(raw) == expected


def test_collapse_spaces_removes_control_characters():
    assert collapse_spaces('A\x00B\x07  C') == 'AB C'
    assert normalize_label(' 7  eb a ') == '7 EB A'


@pytest.mark.parametrize('value', ['=cmd|calc', '+1+1', '-2+3', '@SUM(A1)'])
def test_csv_safe_neutralizes_formulas(value):
    assert csv_safe(value) == "'" + value


def test_csv_safe_leaves_normal_values():
    assert csv_safe('JEAN DUPONT') == 'JEAN DUPONT'
    assert csv_safe(12) == 12


def test_safe_json_escapes_html():
    assert '<' not in safe_json({'a': '</script><b>'})


# ── Pourcentages ─────────────────────────────────────────────────

@pytest.mark.parametrize('raw, expected', [
    ('75', '75.00'), ('75,5', '75.50'), ('75 %', '75.00'), ('75%', '75.00'),
    (87.5, '87.50'), (0, '0.00'), ('100', '100.00'), (' 62.345 ', '62.35'),
])
def test_parse_percentage_accepts_common_formats(raw, expected):
    assert parse_percentage(raw) == (Decimal(expected), None)


@pytest.mark.parametrize('raw', [None, '', '  ', 'N/A', 'n/a', '-', '/', '—'])
def test_parse_percentage_empty_markers_mean_no_grade(raw):
    value, error = parse_percentage(raw)
    assert value is None and error is None


@pytest.mark.parametrize('raw', ['abc', '101', '-5', 'NaN', 'Infinity', 'sNaN', '1e400', True, '12,3,4'])
def test_parse_percentage_rejects_invalid_values(raw):
    value, error = parse_percentage(raw)
    assert value is None and error


def test_parse_percentage_excel_percent_format_and_fractions():
    assert parse_percentage(0.875, percent_format=True) == (Decimal('87.50'), None)
    assert parse_percentage(0.5, fraction_scaled=True) == (Decimal('50.00'), None)
    # Un texte déjà suffixé par % n'est pas multiplié une seconde fois
    assert parse_percentage('75%', fraction_scaled=True) == (Decimal('75.00'), None)


# ── Validation d'une ligne ───────────────────────────────────────

def _cells(name='Jean Dupont', pct='75', classe='7 EB A', section='Secondaire', year='2024 - 2025'):
    return {
        'Nom complet': Cell(name, False), 'Pourcentage': Cell(pct, False), 'Classe': Cell(classe, False),
        'Section': Cell(section, False), 'Année scolaire': Cell(year, False),
    }


def test_validate_row_cleans_values():
    cleaned, errors = validate_row(_cells())
    assert not errors
    assert cleaned == {
        'full_name': 'JEAN DUPONT', 'percentage': Decimal('75.00'), 'classroom_name': '7 EB A',
        'section': 'SECONDAIRE', 'year_label': '2024-2025',
    }


def test_validate_row_reports_every_problem():
    _, errors = validate_row(_cells(name='', pct='abc', classe=None, section='', year=None))
    assert len(errors) == 5


def test_validate_row_rejects_values_too_long_for_the_database():
    _, errors = validate_row(_cells(name='X' * 201, classe='C' * 101))
    assert any('Nom complet' in e for e in errors) and any('Classe' in e for e in errors)


def test_validate_row_strips_control_characters():
    cleaned, errors = validate_row(_cells(name='JEAN\x00 DUPONT'))
    assert not errors and cleaned['full_name'] == 'JEAN DUPONT'


def test_validate_row_numeric_class_cell():
    cleaned, _ = validate_row(_cells(classe=7.0))
    assert cleaned['classroom_name'] == '7'


# ── Lecture des classeurs ────────────────────────────────────────

def test_read_xlsx_returns_real_excel_row_numbers(make_xlsx):
    path = make_xlsx([('A', 50, '7A', 'SEC', '2024-2025'), ('B', 60, '7A', 'SEC', '2024-2025')])
    sheets, ignored = read_workbook(path)
    assert [n for n, _ in sheets[0].rows] == [2, 3]
    assert ignored == []


def test_header_can_follow_title_rows(make_xlsx):
    path = make_xlsx([('A', 50, '7A', 'SEC', '2024-2025')], title_rows=3)
    sheets, _ = read_workbook(path)
    assert [n for n, _ in sheets[0].rows] == [5]


def test_headers_are_matched_without_case_or_accents(make_xlsx):
    path = make_xlsx([('A', 50, '7A', 'SEC', '2024-2025')],
                     headers=['nom COMPLET', 'pourcentage', 'CLASSE', 'section', 'annee scolaire'])
    sheets, _ = read_workbook(path)
    assert len(sheets[0].rows) == 1


def test_blank_rows_are_skipped(make_xlsx):
    path = make_xlsx([('A', 50, '7A', 'SEC', '2024-2025'), (None, None, None, None, None),
                      ('B', 60, '7A', 'SEC', '2024-2025')])
    sheets, _ = read_workbook(path)
    assert [n for n, _ in sheets[0].rows] == [2, 4]


def test_all_sheets_are_read_and_invalid_ones_reported(make_xlsx):
    path = make_xlsx(
        [('A', 50, '7A', 'SEC', '2024-2025')],
        extra_sheets={'Deuxième': [HEADERS_ROW, ('B', 60, '8A', 'SEC', '2024-2025')],
                      'Notes': [('juste', 'du texte')]},
    )
    sheets, ignored = read_workbook(path)
    assert [s.name for s in sheets] == ['Feuil1', 'Deuxième']
    assert [name for name, _ in ignored] == ['Notes']


HEADERS_ROW = ('Nom complet', 'Pourcentage', 'Classe', 'Section', 'Année scolaire')


def test_missing_columns_are_named(make_xlsx):
    path = make_xlsx([('A', 50)], headers=['Nom complet', 'Pourcentage'])
    with pytest.raises(ImportFileError) as error:
        read_workbook(path)
    assert set(error.value.missing_columns) == {'Classe', 'Section', 'Année scolaire'}


def test_file_without_data_rows_is_rejected(make_xlsx):
    with pytest.raises(ImportFileError):
        read_workbook(make_xlsx([]))


def test_excel_percent_cells_are_detected(make_xlsx):
    path = make_xlsx([('A', 0.875, '7A', 'SEC', '2024-2025')], pct_format=True)
    sheets, _ = read_workbook(path)
    cells = sheets[0].rows[0][1]
    assert cells['Pourcentage'].percent is True
    cleaned, errors = validate_row(cells)
    assert not errors and cleaned['percentage'] == Decimal('87.50')


def test_column_of_fractions_is_scaled(make_xlsx):
    path = make_xlsx([('A', 0.75, '7A', 'SEC', '2024-2025'), ('B', 0.5, '7A', 'SEC', '2024-2025')])
    sheet = read_workbook(path)[0][0]
    assert sheet.fraction_scaled
    assert validate_row(sheet.rows[0][1], sheet.fraction_scaled)[0]['percentage'] == Decimal('75.00')


def test_normal_percentages_are_not_scaled(make_xlsx):
    path = make_xlsx([('A', 75, '7A', 'SEC', '2024-2025'), ('B', 0.5, '7A', 'SEC', '2024-2025')])
    assert not read_workbook(path)[0][0].fraction_scaled


def test_text_file_renamed_to_xlsx_is_rejected(tmp_path):
    path = tmp_path / 'faux.xlsx'
    path.write_text('ceci n’est pas un classeur')
    with pytest.raises(ImportFileError):
        read_workbook(str(path))


def test_corrupted_zip_is_rejected(tmp_path):
    path = tmp_path / 'casse.xlsx'
    path.write_bytes(b'PK\x03\x04' + b'\x00' * 100)
    with pytest.raises(ImportFileError):
        read_workbook(str(path))


def test_xls_files_are_supported(make_xls):
    path = make_xls([('Jean Dupont', 75, '7A', 'SEC', '2024-2025')])
    sheets, _ = read_workbook(path)
    cleaned, errors = validate_row(sheets[0].rows[0][1])
    assert not errors and cleaned['full_name'] == 'JEAN DUPONT' and cleaned['percentage'] == Decimal('75.00')


def test_xls_percent_format_is_detected(make_xls):
    path = make_xls([('Jean Dupont', 0.875, '7A', 'SEC', '2024-2025')], percent_rows=True)
    cells = read_workbook(path)[0][0].rows[0][1]
    assert validate_row(cells)[0]['percentage'] == Decimal('87.50')
