"""
Celery tasks for the courses app.
Example tasks for sending notifications and processing course data.
"""

import logging
from celery import shared_task

from tools.notification_core import canonical_json, render_notification_payload, send_email_payload, sha256_hexdigest

logger = logging.getLogger(__name__)


@shared_task
def debug_task():
    """Simple debug task to test if Celery is working."""
    logger.info("Debug task executed successfully")
    return {'status': 'success', 'message': 'Celery task executed'}


@shared_task(bind=True, max_retries=3)
def send_course_notification(self, course_id, user_email, subject, message):
    """
    Send email notification to user about course updates.
    
    Args:
        course_id: ID of the course
        user_email: Email address of the recipient
        subject: Email subject
        message: Email message body
    """
    dedupe_key = sha256_hexdigest(canonical_json({
        "course_id": course_id,
        "user_email": user_email,
        "subject": subject,
        "message": message,
    }))

    try:
        rendered = render_notification_payload(
            "course_notification",
            {
                "recipient_email": user_email,
                "subject": subject,
                "message": message,
                "notification_id": dedupe_key,
                "dedupe_key": dedupe_key,
                "correlation_id": f"course:{course_id}",
                "metadata": {"course_id": course_id},
            },
        )
        result = send_email_payload(rendered)
    except Exception as exc:
        logger.error("Failed to send notification to %s for course %s: %s", user_email, course_id, exc)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))

    if result.get("success"):
        logger.info("Notification sent to %s for course %s", user_email, course_id)
        return result

    logger.error("Failed to send notification to %s for course %s: %s", user_email, course_id, result.get("errors"))
    if result.get("data", {}).get("retryable") and self.request.retries < self.max_retries:
        raise self.retry(exc=Exception(result.get("message", "retryable notification failure")), countdown=60 * (2 ** self.request.retries))

    return result


@shared_task
def process_enrollment_progress(enrollment_id):
    """
    Process and update enrollment progress.
    Can be triggered after course completion.
    
    Args:
        enrollment_id: ID of the enrollment to process
    """
    try:
        logger.info(f"Processing enrollment progress for {enrollment_id}")
        # Add your processing logic here
    except Exception as exc:
        logger.error(f"Error processing enrollment {enrollment_id}: {str(exc)}")
        raise


@shared_task
def generate_course_certificate(enrollment_id, user_id):
    """
    Generate certificate for user upon course completion.
    
    Args:
        enrollment_id: ID of the enrollment
        user_id: ID of the user
    """
    try:
        logger.info(f"Generating certificate for user {user_id}, enrollment {enrollment_id}")
        # Add certificate generation logic here
    except Exception as exc:
        logger.error(f"Error generating certificate: {str(exc)}")
        raise


@shared_task
def cleanup_old_progress_records(days=30):
    """
    Clean up old progress records older than specified days.
    Can be used with Celery Beat for periodic cleanup.
    
    Args:
        days: Number of days to keep progress records
    """
    try:
        logger.info(f"Cleaning up progress records older than {days} days")
        # Add cleanup logic here
    except Exception as exc:
        logger.error(f"Error during cleanup: {str(exc)}")
        raise


@shared_task(bind=True)
def sync_scorm_registration_progress(self, enrollment_id, max_attempts=60, interval_seconds=15, attempt=0):
    """
    Poll SCORM Cloud in the background and keep the enrollment progress fresh.

    The task reschedules itself until the registration completes or max_attempts is reached.
    """
    from decimal import Decimal
    from .models import CourseEnrollment
    from .services import (
        get_course_scorm_expected_seconds,
        get_scorm_registration_progress,
        normalize_scorm_completion_amount,
    )
    from .views import CourseEnrollmentViewSet

    try:
        enrollment = CourseEnrollment.objects.select_related('course').get(id=enrollment_id)
    except CourseEnrollment.DoesNotExist:
        logger.warning(f"SCORM sync skipped: enrollment {enrollment_id} not found")
        return {'status': 'missing_enrollment'}

    if not enrollment.scorm_registration_id:
        logger.info(f"SCORM sync skipped: enrollment {enrollment_id} has no registration id")
        return {'status': 'no_registration'}

    try:
        progress = get_scorm_registration_progress(enrollment.scorm_registration_id)
        expected_seconds = get_course_scorm_expected_seconds(enrollment.course)
        completion_amount = normalize_scorm_completion_amount(progress, expected_seconds=expected_seconds)

        if completion_amount is not None:
            completion_amount = max(0.0, min(100.0, float(completion_amount)))
            current_progress = float(enrollment.progress_percentage or 0)

            if completion_amount > current_progress:
                enrollment.progress_percentage = Decimal(str(round(completion_amount, 2)))
                if completion_amount >= 100:
                    enrollment.status = 'completed'
                    if not enrollment.completed_at:
                        from django.utils import timezone
                        enrollment.completed_at = timezone.now()
                enrollment.save(update_fields=['progress_percentage', 'status', 'completed_at'])
                if enrollment.status == 'completed':
                    from accounts.notification_service import notify_course_completion
                    notify_course_completion(enrollment)
                CourseEnrollmentViewSet.broadcast_progress(enrollment.id)

        done = completion_amount is not None and completion_amount >= 100
        if done or attempt >= max_attempts - 1:
            return {
                'status': 'finished',
                'completion_amount': completion_amount,
            }

        self.apply_async(
            args=[enrollment_id],
            kwargs={'max_attempts': max_attempts, 'interval_seconds': interval_seconds, 'attempt': attempt + 1},
            countdown=interval_seconds,
        )
        return {
            'status': 'scheduled',
            'completion_amount': completion_amount,
        }

    except Exception as exc:
        logger.warning(f"SCORM sync failed for enrollment {enrollment_id}: {exc}")
        if max_attempts > 1:
            self.apply_async(
                args=[enrollment_id],
                kwargs={'max_attempts': max_attempts, 'interval_seconds': interval_seconds, 'attempt': attempt + 1},
                countdown=interval_seconds,
            )
        return {'status': 'retry_scheduled', 'error': str(exc)}


@shared_task(bind=True, max_retries=2)
def process_scorm_upload_async(self, course_id, scorm_course_id, temp_file_path, may_create_new_version=True):
    """
    Async task to upload SCORM package to SCORM Cloud.
    File is saved on shared Docker volume accessible by both backend and celery.
    This prevents blocking the HTTP request during the upload.
    
    Args:
        course_id: Django Course model ID
        scorm_course_id: SCORM Cloud course ID (e.g., 'local_course_5')
        temp_file_path: Path to the temp zip file (shared volume /code/.scorm_uploads/...)
        may_create_new_version: Whether to create new version if course exists
    """
    import os
    from .models import Course
    from .scorm_client import get_scorm_client
    from .services import _extract_import_job_id, _is_scorm_quota_error, cleanup_orphaned_scorm_courses
    import rustici_software_cloud_v2 as scorm_cloud
    
    try:
        logger.info(f"[Task {self.request.id}] Starting SCORM upload for course {course_id}")
        
        # Check if file exists on shared volume
        if not os.path.exists(temp_file_path):
            raise FileNotFoundError(f"Temp file not found on shared volume: {temp_file_path}")
        
        file_size_mb = os.path.getsize(temp_file_path) / (1024 * 1024)
        logger.info(f"[Task {self.request.id}] Found SCORM file: {temp_file_path} ({file_size_mb:.2f} MB)")
        logger.debug("[Task %s] Found file %s (%.2f MB)", self.request.id, temp_file_path, file_size_mb)
        
        course = Course.objects.get(id=course_id)
        api = scorm_cloud.CourseApi(get_scorm_client())
        
        # 2-Step Upload Process: More robust for large files and library bugs
        try:
            import requests
            
            # Step 1: Get upload destination
            logger.info(f"[Task {self.request.id}] Getting upload destination...")
            dest_url = api.get_upload_destination()
            # Handle different response types (some versions return an object, some a string)
            actual_url = getattr(dest_url, 'result', dest_url)
            if not isinstance(actual_url, str):
                actual_url = str(actual_url)
            
            logger.info(f"[Task {self.request.id}] Uploading to: {actual_url}")
            
            # Step 2: Upload file directly via requests
            with open(temp_file_path, 'rb') as f:
                upload_response = requests.put(actual_url, data=f, headers={'Content-Type': 'application/zip'})
                upload_response.raise_for_status()
            
            logger.info(f"[Task {self.request.id}] Upload successful. Starting import...")
            
            # Step 3: Trigger import from the uploaded URL
            job = api.create_import_course_job(
                scorm_course_id,
                url=actual_url,
                may_create_new_version=may_create_new_version
            )
            
            logger.info(f"[Task {self.request.id}] Import job created: {job}")
            logger.debug("[Task %s] SCORM Import job created: %s", self.request.id, job)
            
        except Exception as api_exc:
            if _is_scorm_quota_error(api_exc):
                logger.warning(
                    f"[Task {self.request.id}] SCORM quota hit for course {course_id}; attempting cleanup and retry"
                )
                deleted_ids = cleanup_orphaned_scorm_courses(keep_course_ids=[scorm_course_id])
                logger.info(f"[Task {self.request.id}] Deleted orphaned SCORM courses: {deleted_ids}")
                if deleted_ids:
                    job = api.create_import_course_job(
                        scorm_course_id,
                        url=actual_url,
                        may_create_new_version=may_create_new_version
                    )
                else:
                    logger.error(f"[Task {self.request.id}] No orphaned SCORM courses were available to delete")
                    raise
            else:
                logger.error(f"[Task {self.request.id}] SCORM Cloud upload/import error: {type(api_exc).__name__}: {str(api_exc)}")
                logger.debug("[Task %s] SCORM API error: %s", self.request.id, str(api_exc))
                raise
        
        # Update course with the stable import job ID extracted from the SDK response.
        import_job_id = _extract_import_job_id(job, scorm_course_id)

        # Save and return
        course.scorm_import_job_id = import_job_id
        course.save(update_fields=['scorm_import_job_id'])
        logger.info(f"[Task {self.request.id}] SCORM upload completed for course {course_id}. Job ID: {import_job_id}")
        logger.debug("[Task %s] SCORM upload succeeded. Import job ID: %s", self.request.id, import_job_id)
        return {'job_id': import_job_id, 'status': 'uploading'}
        
    except FileNotFoundError as fnf_exc:
        logger.error(f"[Task {self.request.id}] File not found on shared volume: {str(fnf_exc)}")
        logger.debug("[Task %s] File not found error: %s", self.request.id, str(fnf_exc))
        # Retry - file might appear on next attempt
        if self.request.retries < self.max_retries:
            countdown = 60 * (2 ** self.request.retries)
            logger.warning(f"[Task {self.request.id}] Retrying in {countdown}s...")
            raise self.retry(exc=fnf_exc, countdown=countdown)
        else:
            logger.error(f"[Task {self.request.id}] Max retries exceeded for missing file")
            raise
    except Exception as exc:
        logger.error(f"[Task {self.request.id}] SCORM upload failed for course {course_id}: {type(exc).__name__}: {str(exc)}", exc_info=True)
        logger.debug("[Task %s] SCORM upload exception: %s", self.request.id, str(exc))
        # Don't retry on SCORM Cloud API errors (e.g., 404, invalid course ID)
        # Only retry on connection/temporary errors
        if "Connection" in str(type(exc).__name__) or "Timeout" in str(type(exc).__name__):
            if self.request.retries < self.max_retries:
                countdown = 60 * (2 ** self.request.retries)
                logger.warning(f"[Task {self.request.id}] Retrying in {countdown}s due to connection error...")
                raise self.retry(exc=exc, countdown=countdown)
        
        # For other errors, fail without retry
        logger.error(f"[Task {self.request.id}] Permanent error - not retrying")
        raise
    
    finally:
        # Clean up temp file
        try:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
                logger.info(f"[Task {self.request.id}] Cleaned up temp file: {temp_file_path}")
        except Exception as cleanup_exc:
            logger.warning(f"[Task {self.request.id}] Failed to cleanup temp file: {str(cleanup_exc)}")


@shared_task(bind=True, max_retries=2)
def process_module_content_scorm_upload_async(self, content_id, scorm_course_id, temp_file_path, may_create_new_version=True):
    """
    Async task to upload a module content file to SCORM Cloud.

    The HTTP request only writes the uploaded file to the shared volume and enqueues
    this task so the browser does not wait for the full SCORM Cloud transfer.
    """
    import os
    from .models import ModuleContent
    from .scorm_client import get_scorm_client
    from .services import _extract_import_job_id, _is_scorm_quota_error, cleanup_orphaned_scorm_courses
    import rustici_software_cloud_v2 as scorm_cloud

    try:
        logger.info(f"[Task {self.request.id}] Starting SCORM upload for content {content_id}")

        if not os.path.exists(temp_file_path):
            raise FileNotFoundError(f"Temp file not found on shared volume: {temp_file_path}")

        file_size_mb = os.path.getsize(temp_file_path) / (1024 * 1024)
        logger.info(f"[Task {self.request.id}] Found SCORM file: {temp_file_path} ({file_size_mb:.2f} MB)")

        content = ModuleContent.objects.get(id=content_id)
        api = scorm_cloud.CourseApi(get_scorm_client())

        try:
            import requests
            actual_url = None

            dest_url = api.get_upload_destination()
            actual_url = getattr(dest_url, 'result', dest_url)
            if not isinstance(actual_url, str):
                actual_url = str(actual_url)

            with open(temp_file_path, 'rb') as file_handle:
                upload_response = requests.put(actual_url, data=file_handle, headers={'Content-Type': 'application/zip'})
                upload_response.raise_for_status()

            job = api.create_import_course_job(
                scorm_course_id,
                url=actual_url,
                may_create_new_version=may_create_new_version,
            )
        except Exception as api_exc:
            if _is_scorm_quota_error(api_exc):
                logger.warning(
                    f"[Task {self.request.id}] SCORM quota hit for content {content_id}; attempting cleanup and retry"
                )
                deleted_ids = cleanup_orphaned_scorm_courses(keep_course_ids=[scorm_course_id])
                logger.info(f"[Task {self.request.id}] Deleted orphaned SCORM courses: {deleted_ids}")
                if deleted_ids:
                    job = api.create_import_course_job(
                        scorm_course_id,
                        url=actual_url,
                        may_create_new_version=may_create_new_version,
                    )
                else:
                    logger.error(f"[Task {self.request.id}] No orphaned SCORM courses were available to delete")
                    raise
            else:
                logger.error(f"[Task {self.request.id}] SCORM Cloud upload/import error: {type(api_exc).__name__}: {str(api_exc)}")
                raise

        import_job_id = _extract_import_job_id(job, scorm_course_id)
        content.scorm_course_id = scorm_course_id
        content.scorm_import_job_id = import_job_id
        content.scorm_status = 'processing'
        content.save(update_fields=['scorm_course_id', 'scorm_import_job_id', 'scorm_status', 'scorm_version'])

        logger.info(f"[Task {self.request.id}] SCORM content upload completed for content {content_id}. Job ID: {import_job_id}")
        return {'job_id': import_job_id, 'status': 'uploading'}

    except FileNotFoundError as fnf_exc:
        logger.error(f"[Task {self.request.id}] File not found on shared volume: {str(fnf_exc)}")
        if self.request.retries < self.max_retries:
            countdown = 60 * (2 ** self.request.retries)
            raise self.retry(exc=fnf_exc, countdown=countdown)
        raise
    except Exception as exc:
        logger.error(f"[Task {self.request.id}] SCORM content upload failed for content {content_id}: {type(exc).__name__}: {str(exc)}", exc_info=True)
        if "Connection" in str(type(exc).__name__) or "Timeout" in str(type(exc).__name__):
            if self.request.retries < self.max_retries:
                countdown = 60 * (2 ** self.request.retries)
                raise self.retry(exc=exc, countdown=countdown)
        raise
    finally:
        try:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
        except Exception as cleanup_exc:
            logger.warning(f"[Task {self.request.id}] Failed to cleanup temp file: {str(cleanup_exc)}")
