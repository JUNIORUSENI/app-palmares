"""Normalisation des libellés (noms d'élèves, classes, années) et utilitaires d'affichage sûrs."""
import json
import re
import unicodedata

_WHITESPACE = re.compile(r'\s+')
# Caractères de contrôle (NUL fait échouer PostgreSQL), tabulations et sauts de ligne exclus
_CONTROL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_YEAR_LABEL = re.compile(r'^(\d{4})\s*[-\u2010-\u2015/]\s*(\d{4})$')
_APOSTROPHES = re.compile(r"['\u2019\u2018`\u00b4]")
_HYPHENS = re.compile(r'[-\u2010-\u2015]')

# Un tableur peut interpréter ces débuts de cellule comme une formule (injection CSV)
_FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


def collapse_spaces(value):
    """Supprime les caractères de contrôle et réduit les espaces multiples à un seul."""
    text = unicodedata.normalize('NFC', str(value if value is not None else ''))
    text = _CONTROL_CHARS.sub('', text)
    return _WHITESPACE.sub(' ', text).strip()


def normalize_label(value):
    """Libellé stocké : espaces nettoyés, majuscules (utilisé pour classes et sections)."""
    return collapse_spaces(value).upper()


def normalize_year_label(value):
    """'2024 - 2025' et '2024/2025' deviennent '2024-2025'."""
    text = normalize_label(value)
    match = _YEAR_LABEL.match(text)
    if match:
        return f'{match.group(1)}-{match.group(2)}'
    return text


def name_key(value):
    """Clé de comparaison d'un nom : insensible à la casse, aux accents, aux espaces,
    aux apostrophes et aux tirets. Deux graphies du même nom donnent la même clé."""
    text = unicodedata.normalize('NFKD', collapse_spaces(value))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    text = _APOSTROPHES.sub('', text)
    text = _HYPHENS.sub(' ', text)
    return _WHITESPACE.sub(' ', text).strip().upper()


def csv_safe(value):
    """Neutralise l'injection de formule dans un export CSV ouvert avec Excel."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def safe_json(data):
    """json.dumps avec échappement des caractères HTML dangereux (<, >, &).
    Indispensable pour injecter du JSON directement dans une balise <script>."""
    return (
        json.dumps(data)
        .replace('<', r'\u003c')
        .replace('>', r'\u003e')
        .replace('&', r'\u0026')
    )
