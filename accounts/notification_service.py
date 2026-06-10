"""
Central notification service: persist to DB and push via Channels WebSocket.
"""

import logging
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

from .models import Notification, User

logger = logging.getLogger(__name__)

VALID_NOTIFICATION_TYPES = {choice[0] for choice in Notification.NOTIFICATION_TYPES}


def _serialize_notification(notification: Notification) -> dict[str, Any]:
    return {
        'id': notification.id,
        'title': notification.title,
        'message': notification.message,
        'notification_type': notification.notification_type,
        'link': notification.link,
        'is_read': notification.is_read,
        'metadata': notification.metadata or {},
        'created_at': notification.created_at.isoformat(),
    }


def _push_realtime(user_id: int, payload: dict[str, Any]) -> None:
    channel_layer = get_channel_layer()
    if channel_layer is None:
        logger.warning('No channel layer configured; skipping realtime push for user %s', user_id)
        return

    try:
        async_to_sync(channel_layer.group_send)(
            f'user_{user_id}',
            {
                'type': 'notification_message',
                'notification': payload,
            },
        )
    except Exception:
        logger.exception('Failed to push notification to user_%s', user_id)


def send_notification(
    user: User,
    title: str,
    message: str,
    notification_type: str = 'general',
    *,
    link: str | None = None,
    metadata: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
    push_realtime: bool = True,
) -> Notification | None:
    """
    Create a notification and optionally push it over WebSocket.

    When dedupe_key is provided, skips creation if an identical notification
    already exists for this user (checked via metadata.dedupe_key).
    """
    if notification_type not in VALID_NOTIFICATION_TYPES:
        notification_type = 'general'

    meta = dict(metadata or {})
    if dedupe_key:
        meta['dedupe_key'] = dedupe_key
        existing = Notification.objects.filter(
            recipient=user,
            metadata__dedupe_key=dedupe_key,
        ).first()
        if existing:
            logger.debug(
                'Skipping duplicate notification (dedupe_key=%s) for user %s',
                dedupe_key,
                user.id,
            )
            return None

    notification = Notification.objects.create(
        recipient=user,
        title=title,
        message=message,
        notification_type=notification_type,
        link=link,
        metadata=meta,
    )

    if push_realtime:
        _push_realtime(user.id, _serialize_notification(notification))

    return notification


def notify_course_enrollment(enrollment) -> Notification | None:
    course = enrollment.course
    student = enrollment.student
    return send_notification(
        student,
        title='Course Enrollment Confirmed',
        message=f'You have been enrolled in "{course.title}".',
        notification_type='course_enrollment',
        link=None,
        metadata={
            'course_id': course.id,
            'enrollment_id': enrollment.id,
        },
        dedupe_key=f'enrollment:{enrollment.id}',
    )


def notify_course_completion(enrollment) -> Notification | None:
    if enrollment.status != 'completed':
        return None

    course = enrollment.course
    student = enrollment.student
    return send_notification(
        student,
        title='Course Completed!',
        message=f'Congratulations! You have completed "{course.title}".',
        notification_type='course_completion',
        metadata={
            'course_id': course.id,
            'enrollment_id': enrollment.id,
        },
        dedupe_key=f'course_completion:{enrollment.id}',
    )


def notify_assignment_graded(attempt) -> Notification | None:
    assessment = attempt.assessment
    student = attempt.student
    score_display = f'{attempt.score}%' if attempt.score is not None else 'N/A'
    return send_notification(
        student,
        title='Assignment Graded',
        message=f'Your assignment "{assessment.title}" has been graded. Score: {score_display}.',
        notification_type='assignment_graded',
        metadata={
            'assessment_id': assessment.id,
            'attempt_id': attempt.id,
            'score': float(attempt.score) if attempt.score is not None else None,
        },
        dedupe_key=f'assignment_graded:{attempt.id}',
    )


def notify_quiz_graded(attempt) -> Notification | None:
    assessment = attempt.assessment
    student = attempt.student
    score_display = f'{attempt.score}%' if attempt.score is not None else 'N/A'
    passed_text = 'Passed' if attempt.passed else 'Not passed'
    return send_notification(
        student,
        title='Quiz Results Available',
        message=f'Your quiz "{assessment.title}" has been graded. Score: {score_display} ({passed_text}).',
        notification_type='quiz_graded',
        metadata={
            'assessment_id': assessment.id,
            'attempt_id': attempt.id,
            'score': float(attempt.score) if attempt.score is not None else None,
            'passed': attempt.passed,
        },
        dedupe_key=f'quiz_graded:{attempt.id}',
    )


def notify_scorm_completion(enrollment) -> Notification | None:
    return notify_course_completion(enrollment)


def notify_system_alert(user: User, title: str, message: str, *, metadata: dict | None = None) -> Notification:
    dedupe_key = None
    if metadata and metadata.get('alert_id'):
        dedupe_key = f"system_alert:{metadata['alert_id']}"
    return send_notification(
        user,
        title=title,
        message=message,
        notification_type='system_alert',
        metadata=metadata,
        dedupe_key=dedupe_key,
    )
