"""
Management command to run Daphne server with WebSocket and ASGI support.
Usage: python manage.py run_daphne
"""

from django.core.management.base import BaseCommand
import subprocess
import sys


class Command(BaseCommand):
    help = 'Run Daphne ASGI server for WebSocket and async support'

    def add_arguments(self, parser):
        parser.add_argument(
            '--bind',
            default='0.0.0.0',
            help='The socket to bind to. Default: 0.0.0.0'
        )
        parser.add_argument(
            '--port',
            type=int,
            default=8000,
            help='The port to bind to. Default: 8000'
        )
        parser.add_argument(
            '--reload',
            action='store_true',
            help='Enable auto-reload on code changes'
        )

    def handle(self, *args, **options):
        bind = options['bind']
        port = options['port']
        reload_flag = options['reload']

        cmd = [
            'daphne',
            '-b', bind,
            '-p', str(port),
        ]

        if reload_flag:
            cmd.append('-v', '3')  # Verbose mode for debugging

        cmd.append('LMS.asgi:application')

        self.stdout.write(
            self.style.SUCCESS(
                f'Starting Daphne server on {bind}:{port}...'
            )
        )
        if reload_flag:
            self.stdout.write(self.style.WARNING('Auto-reload enabled'))

        try:
            subprocess.run(cmd)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('Shutting down Daphne server...'))
            sys.exit(0)
