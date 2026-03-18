import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE',
                      os.environ.get('DJANGO_SETTINGS_MODULE', 'config.settings.prod'))

app = Celery('palmares')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
