from .models import Badge, StudentBadge

def issue_badge_if_eligible(student, course, assessment_score=None, scorm_score=None, scorm_passed=None):
    """
    Evaluates all badges linked to a course and issues them if criteria are met.
    Returns a list of newly created StudentBadge instances.
    """
    badges = Badge.objects.filter(course=course)
    issued_badges = []

    for badge in badges:
        criteria = badge.criteria or {}
        criteria_type = criteria.get('type')
        min_score = criteria.get('min_score', 0)
        
        is_eligible = False

        if criteria_type == 'scorm':
            if scorm_passed is True:
                is_eligible = True
            elif scorm_score is not None and float(scorm_score) >= float(min_score):
                is_eligible = True
                
        elif criteria_type == 'assessment':
            if assessment_score is not None and float(assessment_score) >= float(min_score):
                is_eligible = True

        if is_eligible:
            # Create StudentBadge if not already earned
            student_badge, created = StudentBadge.objects.get_or_create(
                student=student,
                badge=badge,
                defaults={
                    'metadata': {
                        'scorm_score': str(scorm_score) if scorm_score is not None else None,
                        'assessment_score': str(assessment_score) if assessment_score is not None else None,
                        'scorm_passed': scorm_passed,
                        'type': criteria_type
                    }
                }
            )
            if created:
                issued_badges.append(student_badge)

    return issued_badges
