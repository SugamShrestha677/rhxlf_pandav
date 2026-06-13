from django.db.models.signals import post_save
from django.dispatch import receiver
from .utils import issue_badge_if_eligible

from courses.models import StudentAssessment 

@receiver(post_save, sender=StudentAssessment)
def check_badge_on_assessment(sender, instance, created, **kwargs):
    # Check passing criteria
    score = getattr(instance, 'score', None)
    is_passed = getattr(instance, 'passed', False)
    
    # Check if instance is linked to a course through an assessment
    assessment = getattr(instance, 'assessment', None)
    if not assessment:
        return
        
    course = getattr(assessment, 'course', None)
    passing_score = getattr(assessment, 'passing_score', 0)

    if course and (is_passed or (score is not None and score >= passing_score)):
        issue_badge_if_eligible(
            student=instance.student,
            course=course,
            assessment_score=score
        )
