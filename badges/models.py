from django.db import models
from django.contrib.auth import get_user_model
from courses.models import Course

User = get_user_model()

class Badge(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField()
    image_url = models.URLField(max_length=500, help_text="Cloudinary URL")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='badges')
    criteria = models.JSONField(
        help_text='e.g., {"type": "scorm", "min_score": 80} or {"type": "assessment", "min_score": 75}'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.course.title})"

class StudentBadge(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='earned_badges')
    badge = models.ForeignKey(Badge, on_delete=models.CASCADE, related_name='earned_by')
    issued_at = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(
        default=dict,
        help_text='e.g., {"score": 85, "type": "scorm"}'
    )

    class Meta:
        unique_together = ('student', 'badge')

    def __str__(self):
        return f"{self.student.email} - {self.badge.name}"
