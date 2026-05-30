"""
Celery configuration for LMS project.
"""

import os
import logging
from celery import Celery
from celery.schedules import crontab

# Set the default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'LMS.settings')

app = Celery('LMS')
logger = logging.getLogger(__name__)

# Load configuration from Django settings with CELERY namespace
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks from all registered Django apps
app.autodiscover_tasks()

# Optional: Define periodic tasks here
app.conf.beat_schedule = {
    # Example periodic task - uncomment and modify as needed
    # 'check-course-deadlines': {
    #     'task': 'courses.tasks.check_course_deadlines',
    #     'schedule': crontab(minute=0, hour='*/6'),  # Every 6 hours
    # },
}

# Celery Configuration
app.conf.update(
    # Task settings
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Kathmandu',
    enable_utc=True,
    
    # Task execution settings
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes hard limit
    task_soft_time_limit=25 * 60,  # 25 minutes soft limit
    
    # Worker settings
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=1000,
)

@app.task(bind=True)
def debug_task(self):
    """Debug task to test Celery setup."""
    logger.debug('Request: %r', self.request)
