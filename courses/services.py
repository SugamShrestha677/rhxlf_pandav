import os
import tempfile
import logging
import rustici_software_cloud_v2 as scorm_cloud
from rustici_software_cloud_v2.api import RegistrationApi
from rustici_software_cloud_v2.models.create_registration_schema import CreateRegistrationSchema
from rustici_software_cloud_v2.models.launch_link_request_schema import LaunchLinkRequestSchema
from rustici_software_cloud_v2.models.learner_schema import LearnerSchema
from django.conf import settings
from .scorm_client import get_scorm_client
from .models import Course

logger = logging.getLogger(__name__)


def _is_scorm_not_found_error(exc: Exception) -> bool:
    """Return True when SCORM Cloud indicates a missing course/registration."""
    error_text = str(exc).lower()
    body = getattr(exc, 'body', None)
    if isinstance(body, str):
        error_text = f"{error_text} {body.lower()}"
    return (
        '404' in error_text
        or 'could not find course id' in error_text
        or 'course not found' in error_text
    )


def _extract_import_job_id(result, scorm_course_id: str) -> str:
    """Extract a stable import job id from the SCORM Cloud SDK response."""
    candidate = None

    for attr_name in ('job_id', 'import_job_id', 'importJobId', 'id', 'result'):
        if hasattr(result, attr_name):
            candidate = getattr(result, attr_name)
            if candidate is not None:
                break

    if candidate is None:
        candidate = result

    if hasattr(candidate, 'result') and getattr(candidate, 'result') is not None:
        candidate = getattr(candidate, 'result')

    return str(candidate).strip()


def _normalize_import_job_candidates(import_job_id: str, scorm_course_id: str | None = None) -> list[str]:
    """Return possible SCORM Cloud import-job ids, newest format first."""
    candidates: list[str] = []

    if import_job_id:
        candidates.append(import_job_id)

    if import_job_id and scorm_course_id:
        combined = f"{import_job_id}{scorm_course_id}"
        if combined not in candidates:
            candidates.append(combined)

    return candidates


def _is_scorm_quota_error(exc: Exception) -> bool:
    """Return True when SCORM Cloud rejects a course import due to account quota."""
    error_text = str(exc).lower()
    body = getattr(exc, 'body', None)
    if isinstance(body, str):
        error_text = f"{error_text} {body.lower()}"
    return 'maximum number of courses for this account type has been reached' in error_text


def list_scorm_cloud_course_ids():
    """Return the current SCORM Cloud course ids visible to this account."""
    api_instance = scorm_cloud.CourseApi(get_scorm_client())
    result = api_instance.get_courses()
    courses = getattr(result, 'courses', None) or []

    course_ids = []
    for course in courses:
        if isinstance(course, dict):
            course_id = course.get('id')
        else:
            course_id = getattr(course, 'id', None)
        if course_id:
            course_ids.append(course_id)
    return course_ids


def cleanup_orphaned_scorm_courses(keep_course_ids: list[str] | None = None, max_delete: int = 5):
    """Delete SCORM Cloud courses that are not referenced by local content records."""
    from .models import Course as CourseModel, ModuleContent

    protected_ids = set(keep_course_ids or [])
    protected_ids.update(
        ModuleContent.objects.exclude(scorm_course_id__isnull=True).values_list('scorm_course_id', flat=True)
    )
    protected_ids.update(
        CourseModel.objects.exclude(scorm_course_id__isnull=True).values_list('scorm_course_id', flat=True)
    )

    deleted_ids = []
    api_instance = scorm_cloud.CourseApi(get_scorm_client())
    for course_id in list_scorm_cloud_course_ids():
        if course_id in protected_ids:
            continue
        try:
            api_instance.delete_course(course_id)
            deleted_ids.append(course_id)
        except Exception as exc:
            logger.warning(f"Failed to delete orphaned SCORM course {course_id}: {exc}")
        if len(deleted_ids) >= max_delete:
            break

    return deleted_ids

def upload_scorm_zip(course_obj, scorm_zip_file, may_create_new_version=True):
    """Queue SCORM upload as async Celery task (non-blocking).
    Saves file to shared Docker volume accessible by both backend and celery containers.
    """
    import os
    import time
    
    scorm_course_id = f"local_course_{course_obj.id}"

    try:
        logger.info(f"Starting SCORM upload for course {course_obj.id}")
        print(f"DEBUG: upload_scorm_zip called for course {course_obj.id}")
        
        # Save file to shared directory within Docker volume (/code/.scorm_uploads)
        # Both backend and celery containers mount .:/code, so this directory is shared
        shared_upload_dir = "/code/.scorm_uploads"
        os.makedirs(shared_upload_dir, exist_ok=True)
        
        temp_file_path = os.path.join(
            shared_upload_dir, 
            f"scorm_{course_obj.id}_{int(time.time())}.zip"
        )
        
        # Write file to shared directory
        with open(temp_file_path, "wb") as temp_file:
            for chunk in scorm_zip_file.chunks():
                temp_file.write(chunk)
        
        file_size_mb = os.path.getsize(temp_file_path) / (1024 * 1024)
        logger.info(f"SCORM zip saved to shared volume: {temp_file_path} ({file_size_mb:.2f} MB)")
        print(f"DEBUG: Saved {file_size_mb:.2f} MB to {temp_file_path}")

        # Queue the upload as an async task (pass file path, not content)
        try:
            from .tasks import process_scorm_upload_async
            logger.info(f"Importing process_scorm_upload_async task")
            print(f"DEBUG: Importing Celery task")
            
            task = process_scorm_upload_async.delay(
                course_id=course_obj.id,
                scorm_course_id=scorm_course_id,
                temp_file_path=temp_file_path,
                may_create_new_version=may_create_new_version
            )
            logger.info(f"SCORM upload queued with task_id: {task.id}")
            print(f"DEBUG: SCORM upload queued with task_id: {task.id}")
            return scorm_course_id, task.id
            
        except ImportError as e:
            logger.error(f"Failed to import Celery task: {str(e)}")
            print(f"DEBUG: Task import error: {str(e)}")
            raise ValueError(f"Celery task unavailable: {str(e)}")
        except Exception as e:
            logger.error(f"Failed to queue Celery task: {str(e)}", exc_info=True)
            print(f"DEBUG: Task queueing error: {str(e)}")
            raise ValueError(f"Failed to queue upload: {str(e)}")

    except Exception as e:
        logger.error(f"SCORM upload preparation failed: {str(e)}", exc_info=True)
        print(f"DEBUG: upload_scorm_zip error: {str(e)}")
        raise e


def upload_content_to_scorm(content_obj, file_to_upload, may_create_new_version: bool = True):
    """Upload a single file content (PDF, MP4, MP3, ZIP) to SCORM Cloud."""
    api_instance = scorm_cloud.CourseApi(get_scorm_client())
    
    # Unique ID for the content item, including course ID to avoid collisions
    course_id = content_obj.module.course.id
    scorm_course_id = f"course_{course_id}_content_{content_obj.id}"
    
    temp_path = None
    try:
        # Get extension from the uploaded file name
        _, ext = os.path.splitext(file_to_upload.name)
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as temp_file:
            for chunk in file_to_upload.chunks():
                temp_file.write(chunk)
            temp_path = temp_file.name

        result = api_instance.create_upload_and_import_course_job(
            scorm_course_id,
            file=temp_path,
            may_create_new_version=may_create_new_version,
        )

        # The SDK can wrap the job id in nested response objects and, in some
        # environments, concatenate the course id onto the returned identifier.
        import_job_id = _extract_import_job_id(result, scorm_course_id)

        logger.info(f"upload_content_to_scorm: course_id={scorm_course_id}, import_job_id={import_job_id}")
        return scorm_course_id, import_job_id
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def get_import_job_status(import_job_id: str, scorm_course_id: str | None = None):
    api_instance = scorm_cloud.CourseApi(get_scorm_client())
    last_exc = None

    for candidate in _normalize_import_job_candidates(import_job_id, scorm_course_id):
        try:
            result = api_instance.get_import_job_status(candidate)
            return {
                'job_id': getattr(result, 'job_id', candidate),
                'status': result.status,
                'message': result.message,
            }
        except Exception as exc:
            last_exc = exc
            if candidate == import_job_id and scorm_course_id and _is_scorm_not_found_error(exc):
                continue
            break

    if last_exc:
        raise last_exc
    raise ValueError('Unable to determine SCORM import job status')
def get_scorm_launch_link(course_obj: Course, user, registration_id: str | None = None):

    if not course_obj.scorm_course_id:
        raise ValueError('SCORM course id is missing')

    if not registration_id:
        registration_id = f"reg_{course_obj.id}_{user.id}"

    client = get_scorm_client()
    registration_api = RegistrationApi(client)
    course_api = scorm_cloud.CourseApi(client)

    # Fail fast with a clear message if the course has not finished importing yet.
    try:
        course_api.get_course(course_obj.scorm_course_id)
    except Exception as exc:
        if _is_scorm_not_found_error(exc):
            raise ValueError(
                f"SCORM course '{course_obj.scorm_course_id}' not found on SCORM Cloud yet. "
                "Wait for import to finish and try again."
            )
        raise

    learner = LearnerSchema(
        id=str(user.id),
        email=user.email,
        first_name=getattr(user, 'first_name', '') or '',
        last_name=getattr(user, 'last_name', '') or '',
    )

    registration_request = CreateRegistrationSchema(
        course_id=course_obj.scorm_course_id,
        learner=learner,
        registration_id=registration_id
    )

    try:
        registration = registration_api.create_registration(registration_request)
    except Exception as e:
        error_msg = str(e).lower()
        # Some API clients put the error in the body attribute
        error_body = getattr(e, 'body', '').lower() if hasattr(e, 'body') else ''
        
        if "already exists" in error_msg or "already exists" in error_body:
            logger.info(f"Registration {registration_id} already exists, proceeding to launch link generation.")
        else:
            logger.error(f"Failed to create SCORM registration: {error_msg} | Body: {error_body}")
            raise e

    local_exit_url = f"{settings.FRONTEND_BASE_URL}/scorm-exit.html"

    launch_request = LaunchLinkRequestSchema(
        redirect_on_exit_url=local_exit_url,
        tracking=True,
    )

    launch_link = registration_api.build_registration_launch_link(
        registration_id,
        launch_request
    )

    url = launch_link.launch_link
    params = "framesetType=none&force=true&wrap=false"

    url = url + ("&" if "?" in url else "?") + params

    return registration_id, url


def get_content_launch_link(content_obj, user, course_id_for_redirect: int):
    """Create a registration and return a launch link for a specific content item."""
    print(">>> USING NEW SCORM FLOW")
    if not content_obj.scorm_course_id:
        raise ValueError('SCORM course id is missing for this content')

    client = get_scorm_client()
    registration_api = RegistrationApi(client)
    course_api = scorm_cloud.CourseApi(client)

    # Verify content package exists before creating registration.
    try:
        course_api.get_course(content_obj.scorm_course_id)
    except Exception as exc:
        if _is_scorm_not_found_error(exc):
            raise ValueError(
                f"SCORM content '{content_obj.scorm_course_id}' is not available on SCORM Cloud yet. "
                "Please wait for processing or re-upload the package."
            )
        raise
    
    # Use a stable registration ID
    registration_id = f"reg_content_{content_obj.id}_{user.id}"
    
    learner = LearnerSchema(
        id=str(user.id),
        email=user.email,
        first_name=getattr(user, 'first_name', '') or '',
        last_name=getattr(user, 'last_name', '') or '',
    )
    registration = CreateRegistrationSchema(
        course_id=content_obj.scorm_course_id,
        learner=learner,
        registration_id=registration_id,
    )
    from django.core.cache import cache
    cache_key = f"scorm_launch_link_{registration_id}_{course_id_for_redirect}"
    
    cached_url = cache.get(cache_key)
    if cached_url:
        return registration_id, cached_url

    try:
        registration_api.create_registration(registration)
    except Exception as e:
        if "already exists" in str(e).lower():
            pass # Continue to get launch link
        else:
            raise Exception(f"SCORM registration failed: {str(e)}")

    redirect_url = f"{settings.FRONTEND_BASE_URL}/student/courses/{course_id_for_redirect}?scorm_exit=true"
    
    local_exit_url = f"{settings.FRONTEND_BASE_URL}/scorm-exit.html"
    launch_request = LaunchLinkRequestSchema(
        redirect_on_exit_url=local_exit_url,
        tracking=True,
    )

    launch_link = registration_api.build_registration_launch_link(registration_id, launch_request)
    
    url = launch_link.launch_link
    # none + force=true is the industry standard for bypassing SCORM Cloud stubs in same-window redirects
    params = "framesetType=none&force=true&wrap=false"
    
    if '?' in url:
        url += f"&{params}"
    else:
        url += f"?{params}"
        
    cache.set(cache_key, url, 3600)  # Cache for 1 hour
    return registration_id, url


def get_scorm_registration_progress(registration_id: str):
    """Fetch progress details for a SCORM registration."""
    registration_api = RegistrationApi(get_scorm_client())
    registration = registration_api.get_registration_progress(registration_id)

    def _enum_value(value):
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return getattr(value, 'value', None) or getattr(value, 'name', None) or str(value)

    return {
        'registration_id': registration.id,
        'completion': _enum_value(registration.registration_completion),
        'completion_amount': registration.registration_completion_amount,
        'success': _enum_value(registration.registration_success),
        'score': getattr(registration.score, 'scaled', None) if registration.score else None,
        'total_seconds_tracked': registration.total_seconds_tracked,
        'last_access_date': registration.last_access_date,
        'completed_date': registration.completed_date,
    }