"""
Management command to run Celery Beat scheduler.
Usage: python manage.py run_celery_beat
"""

from django.core.management.base import BaseCommand
import subprocess
import sys


class Command(BaseCommand):
    help = 'Run Celery Beat scheduler for periodic tasks'

    def add_arguments(self, parser):
        parser.add_argument(
            '--loglevel',
            default='info',
            choices=['debug', 'info', 'warning', 'error'],
            help='Logging level. Default: info'
        )
        parser.add_argument(
            '--scheduler',
            default='django_celery_beat.schedulers:DatabaseScheduler',
            help='Scheduler backend. Default: DatabaseScheduler'
        )

    def handle(self, *args, **options):
        loglevel = options['loglevel']
        scheduler = options['scheduler']

        cmd = [
            'celery',
            '-A', 'LMS',
            'beat',
            '-l', loglevel,
            '--scheduler', scheduler,
        ]

        self.stdout.write(
            self.style.SUCCESS(
                f'Starting Celery Beat scheduler...'
            )
        )
        self.stdout.write(self.style.WARNING(f'Using scheduler: {scheduler}'))

        try:
            subprocess.run(cmd)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('Shutting down Celery Beat...'))
            sys.exit(0)
