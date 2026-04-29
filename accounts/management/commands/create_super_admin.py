from django.core.management.base import BaseCommand
from accounts.models import User


class Command(BaseCommand):
    help = 'Create super admin user'

    def handle(self, *args, **options):
        email = input('Super admin email: ').strip()
        
        if User.objects.filter(email=email).exists():
            self.stdout.write(self.style.WARNING('User already exists'))
            return
        
        password = input('Password: ').strip()
        
        user = User.objects.create_superuser(
            email=email,
            password=password,
            role='super_admin'
        )
        
        self.stdout.write(
            self.style.SUCCESS(f'Super admin created: {user.email}')
        )