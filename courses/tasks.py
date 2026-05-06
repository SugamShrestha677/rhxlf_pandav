from __future__ import annotations

import os

from celery import shared_task

from .models import Course


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def process_scorm_upload_task(self, course_id: int, temp_path: str, may_create_new_version: bool = True):
    course = Course.objects.get(id=course_id)
    try:
        # Lazy import so the task module can be imported even if SCORM SDK is absent
        from .services import upload_scorm_zip_from_path

        scorm_course_id, import_job_id = upload_scorm_zip_from_path(
            course,
            temp_path,
            may_create_new_version=may_create_new_version,
        )

        course.is_scorm = True
        course.scorm_course_id = scorm_course_id
        course.scorm_import_job_id = import_job_id
        course.save(update_fields=['is_scorm', 'scorm_course_id', 'scorm_import_job_id'])

        return {
            'course_id': course_id,
            'scorm_course_id': scorm_course_id,
            'import_job_id': import_job_id,
        }
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)