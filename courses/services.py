# courses/services.py
import os
import tempfile
import rustici_software_cloud_v2 as scorm_cloud
from rustici_software_cloud_v2.api import RegistrationApi
from rustici_software_cloud_v2.models.create_registration_schema import CreateRegistrationSchema
from rustici_software_cloud_v2.models.launch_link_request_schema import LaunchLinkRequestSchema
from rustici_software_cloud_v2.models.learner_schema import LearnerSchema
from django.conf import settings
from django.conf import settings
from .scorm_client import get_scorm_client
from .models import Course

def upload_scorm_zip(course_obj: Course, scorm_zip_file, may_create_new_version: bool = True):
    """Upload a SCORM zip and start a SCORM Cloud import job."""
    api_instance = scorm_cloud.CourseApi(get_scorm_client())
    course_id = f"local_course_{course_obj.id}"
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_file:
            for chunk in scorm_zip_file.chunks():
                temp_file.write(chunk)
            temp_path = temp_file.name

        result = api_instance.create_upload_and_import_course_job(
            course_id,
            file=temp_path,
            may_create_new_version=may_create_new_version,
        )

        return course_id, result.result
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def upload_content_to_scorm(content_obj, file_to_upload, may_create_new_version: bool = True):
    """Upload a single file content (PDF, MP4, MP3) to SCORM Cloud."""
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

        return scorm_course_id, result.result
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def get_import_job_status(import_job_id: str):
    api_instance = scorm_cloud.CourseApi(get_scorm_client())
    result = api_instance.get_import_job_status(import_job_id)
    return {
        'job_id': result.job_id,
        'status': result.status,
        'message': result.message,
    }


def get_scorm_launch_link(course_obj: Course, user, registration_id: str | None = None):
    """Create (if needed) a registration and return a launch link for the user."""
    if not course_obj.scorm_course_id:
        raise ValueError('SCORM course id is missing')

    registration_api = RegistrationApi(get_scorm_client())

    if not registration_id:
        registration_id = f"reg_{course_obj.id}_{user.id}"
        learner = LearnerSchema(
            id=str(user.id),
            email=user.email,
            first_name=getattr(user, 'first_name', '') or '',
            last_name=getattr(user, 'last_name', '') or '',
        )
        registration = CreateRegistrationSchema(
            course_id=course_obj.scorm_course_id,
            learner=learner,
            registration_id=registration_id,
        )
        try:
            registration_api.create_registration(registration)
        except Exception:
            # Registration might already exist; continue to launch
            pass

    redirect_url = f"{settings.FRONTEND_BASE_URL}/student/courses/{course_obj.id}"
    launch_request = LaunchLinkRequestSchema(
        redirect_on_exit_url=redirect_url,
        tracking=True,
    )
    launch_link = registration_api.build_registration_launch_link(registration_id, launch_request)
    
    # Append framesetType=none to avoid "Launched in new window" message and force iframe rendering
    url = launch_link.launch_link
    if '?' in url:
        url += '&framesetType=none'
    else:
        url += '?framesetType=none'
        
    return registration_id, url


def get_content_launch_link(content_obj, user, course_id_for_redirect: int):
    """Create a registration and return a launch link for a specific content item."""
    if not content_obj.scorm_course_id:
        raise ValueError('SCORM course id is missing for this content')

    registration_api = RegistrationApi(get_scorm_client())
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
    
    try:
        registration_api.create_registration(registration)
    except Exception:
        # Already exists
        pass

    redirect_url = f"{settings.FRONTEND_BASE_URL}/student/courses/{course_id_for_redirect}"
    launch_request = LaunchLinkRequestSchema(
        redirect_on_exit_url=redirect_url,
        tracking=True,
    )
    launch_link = registration_api.build_registration_launch_link(registration_id, launch_request)
    
    # Append framesetType=none to avoid "Launched in new window" message and force iframe rendering
    url = launch_link.launch_link
    if '?' in url:
        url += '&framesetType=none'
    else:
        url += '?framesetType=none'
        
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