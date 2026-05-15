"""
Management command to run Celery worker.
Usage: python manage.py run_celery_worker
"""

from django.core.management.base import BaseCommand
import subprocess
import sys


class Command(BaseCommand):
    help = 'Run Celery worker for async task processing'

    def add_arguments(self, parser):
        parser.add_argument(
            '--loglevel',
            default='info',
            choices=['debug', 'info', 'warning', 'error'],
            help='Logging level. Default: info'
        )
        parser.add_argument(
            '--concurrency',
            type=int,
            default=4,
            help='Number of concurrent worker processes. Default: 4'
        )
        parser.add_argument(
            '--queue',
            default='celery',
            help='Specific queue to listen on. Default: celery'
        )

    def handle(self, *args, **options):
        loglevel = options['loglevel']
        concurrency = options['concurrency']
        queue = options['queue']

        cmd = [
            'celery',
            '-A', 'LMS',
            'worker',
            '-l', loglevel,
            '-c', str(concurrency),
            '-Q', queue,
            '--loglevel', loglevel,
        ]

        self.stdout.write(
            self.style.SUCCESS(
                f'Starting Celery worker with concurrency={concurrency}, queue={queue}...'
            )
        )

        try:
            subprocess.run(cmd)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('Shutting down Celery worker...'))
            sys.exit(0)
