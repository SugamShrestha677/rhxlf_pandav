"""
Management command to run Flower (Celery monitoring UI).
Usage: python manage.py run_flower
"""

from django.core.management.base import BaseCommand
import subprocess
import sys


class Command(BaseCommand):
    help = 'Run Flower monitoring UI for Celery tasks'

    def add_arguments(self, parser):
        parser.add_argument(
            '--port',
            type=int,
            default=5555,
            help='Port to run Flower on. Default: 5555'
        )
        parser.add_argument(
            '--address',
            default='0.0.0.0',
            help='Address to bind to. Default: 0.0.0.0'
        )
        parser.add_argument(
            '--basic-auth',
            help='Basic auth credentials (username:password)'
        )

    def handle(self, *args, **options):
        port = options['port']
        address = options['address']
        basic_auth = options.get('basic_auth')

        cmd = [
            'celery',
            '-A', 'LMS',
            'flower',
            '--port=' + str(port),
            '--address=' + address,
        ]

        if basic_auth:
            cmd.append(f'--basic-auth={basic_auth}')

        self.stdout.write(
            self.style.SUCCESS(
                f'Starting Flower on {address}:{port}...'
            )
        )
        self.stdout.write(self.style.WARNING(f'Access Flower at http://localhost:{port}'))

        try:
            subprocess.run(cmd)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('Shutting down Flower...'))
            sys.exit(0)
