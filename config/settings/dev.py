from .base import *

DEBUG = True
ALLOWED_HOSTS = ['*']

# Afficher les emails dans la console en dev
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Barre de debug (optionnel, décommenter si django-debug-toolbar installé)
# INSTALLED_APPS += ['debug_toolbar']
# MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware']
# INTERNAL_IPS = ['127.0.0.1']
