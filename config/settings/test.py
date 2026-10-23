from .base import *

DEBUG = False
ALLOWED_HOSTS = ['testserver', 'localhost']

# Hachage rapide : les tests créent beaucoup d'utilisateurs
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# Fichiers téléversés dans un dossier temporaire, jamais dans media/
import tempfile
MEDIA_ROOT = tempfile.mkdtemp(prefix='palmares-test-media-')

# Pas besoin de collectstatic pendant les tests
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}

# Les tâches Celery s'exécutent immédiatement, sans Redis
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = False
CELERY_BROKER_URL = 'memory://'
CELERY_RESULT_BACKEND = 'cache+memory://'
