from django.core.management.base import BaseCommand
from badges.models import Badge
from courses.models import Course

class Command(BaseCommand):
    help = 'Imports pre-uploaded Cloudinary badges for specific courses.'

    def handle(self, *args, **kwargs):
        # Update IDs or URLs to match your project exactly
        badges_data = [
            {
                'course_title': 'Python', 
                'name': 'Python Certified',
                'description': 'Awarded for completing the Python course with a passing score.',
                'image_url': 'https://res.cloudinary.com/YOUR_URL/python_badge.png', # User will update this
                'criteria': {"type": "scorm", "min_score": 80}
            },
            {
                'course_title': 'Django',
                'name': 'Django Developer',
                'description': 'Awarded for completing the Django assessment.',
                'image_url': 'https://res.cloudinary.com/YOUR_URL/django_badge.png', # User will update this
                'criteria': {"type": "assessment", "min_score": 75}
            },
            {
                'course_title': 'Laravel',
                'name': 'Laravel Artisan',
                'description': 'Awarded for passing the Laravel course.',
                'image_url': 'https://res.cloudinary.com/YOUR_URL/laravel_badge.png', # User will update this
                'criteria': {"type": "scorm", "min_score": 80}
            },
            {
                'course_title': 'n8n',
                'name': 'n8n Automator',
                'description': 'Awarded for completing n8n training.',
                'image_url': 'https://res.cloudinary.com/YOUR_URL/n8n_badge.png', # User will update this
                'criteria': {"type": "assessment", "min_score": 80}
            }
        ]

        for data in badges_data:
            courses = Course.objects.filter(title__icontains=data['course_title'])
            if not courses.exists():
                self.stdout.write(self.style.ERROR(f"Course matching '{data['course_title']}' not found."))
                continue
                
            course = courses.first()
            badge, created = Badge.objects.get_or_create(
                name=data['name'],
                course=course,
                defaults={
                    'description': data['description'],
                    'image_url': data['image_url'],
                    'criteria': data['criteria']
                }
            )
            
            if created:
                self.stdout.write(self.style.SUCCESS(f"Created badge '{badge.name}' for course '{course.title}'"))
            else:
                self.stdout.write(self.style.WARNING(f"Badge '{badge.name}' already exists for course '{course.title}'"))
