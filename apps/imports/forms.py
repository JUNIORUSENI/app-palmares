import os
from django import forms
from .models import SourceFile

_ALLOWED_EXTENSIONS = {'.xlsx', '.xls'}
_MAX_UPLOAD_MB = 20
_MAX_UPLOAD_BYTES = _MAX_UPLOAD_MB * 1024 * 1024


class SourceFileUploadForm(forms.ModelForm):
    class Meta:
        model = SourceFile
        fields = ['file']
        widgets = {
            'file': forms.FileInput(attrs={'accept': '.xlsx,.xls'}),
        }
        labels = {
            'file': 'Fichier Excel (.xlsx)',
        }

    def clean_file(self):
        f = self.cleaned_data.get('file')
        if not f:
            return f

        # Validation de l'extension (côté serveur)
        ext = os.path.splitext(f.name)[1].lower()
        if ext not in _ALLOWED_EXTENSIONS:
            raise forms.ValidationError(
                "Format non accepté. Seuls les fichiers .xlsx et .xls sont autorisés."
            )

        # Validation de la taille
        if f.size > _MAX_UPLOAD_BYTES:
            raise forms.ValidationError(
                f"Fichier trop volumineux ({f.size // (1024*1024)} Mo). "
                f"Limite : {_MAX_UPLOAD_MB} Mo."
            )

        return f
