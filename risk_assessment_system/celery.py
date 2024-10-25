# risk_assessment_system/celery.py

import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'risk_assessment_system.settings')

app = Celery('risk_assessment_system')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()