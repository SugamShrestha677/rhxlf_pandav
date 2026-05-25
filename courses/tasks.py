"""
Celery tasks for the courses app.
Example tasks for sending notifications and processing course data.
"""

from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
import logging

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
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user_email],
            fail_silently=False,
        )
        logger.info(f"Notification sent to {user_email} for course {course_id}")
    except Exception as exc:
        logger.error(f"Failed to send notification: {str(exc)}")
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


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
        print(f"DEBUG: Found file {temp_file_path} ({file_size_mb:.2f} MB)")
        
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
            print(f"DEBUG: SCORM Import job created: {job}")
            
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
                print(f"DEBUG: SCORM API error: {str(api_exc)}")
                raise
        
        # Update course with the stable import job ID extracted from the SDK response.
        import_job_id = _extract_import_job_id(job, scorm_course_id)

        # Save and return
        course.scorm_import_job_id = import_job_id
        course.save(update_fields=['scorm_import_job_id'])
        logger.info(f"[Task {self.request.id}] SCORM upload completed for course {course_id}. Job ID: {import_job_id}")
        print(f"DEBUG: SCORM upload succeeded. Import job ID: {import_job_id}")
        return {'job_id': import_job_id, 'status': 'uploading'}
        
    except FileNotFoundError as fnf_exc:
        logger.error(f"[Task {self.request.id}] File not found on shared volume: {str(fnf_exc)}")
        print(f"DEBUG: File not found error: {str(fnf_exc)}")
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
        print(f"DEBUG: SCORM upload exception: {str(exc)}")
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
