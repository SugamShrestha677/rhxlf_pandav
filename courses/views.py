import os
import tempfile

from celery.result import AsyncResult
from django.core.cache import cache
from django.conf import settings
from rest_framework import viewsets, status, permissions
from rest_framework import serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db import models as db_models
from cloudinary.uploader import upload
from django.db.models.functions import TruncDate
from datetime import timedelta

from .models import (
    Category, Course, CourseModule, ModuleContent, CourseEnrollment, CourseResource,
    StudentModuleProgress, StudentContentProgress,
    Assessment, StudentAssessment, Certificate,
    CourseReview, CourseAnnouncement
)
from .serializers import (
    CategorySerializer, CourseSerializer, CourseCreateSerializer,
    CourseModuleSerializer, CourseModuleBasicSerializer,
    ModuleContentSerializer, AssessmentSerializer,
    CourseEnrollmentSerializer, StudentAssessmentSerializer,
    CertificateSerializer, CourseReviewSerializer,
    CourseAnnouncementSerializer, CourseListSerializer,
    EnrollmentWithCourseSerializer, ScormUploadSerializer,
    CourseResourceSerializer
)
# Import SCORM service functions lazily inside SCORM-related actions to
# avoid requiring the SCORM SDK at import time during lightweight tests.
from .permissions import CanManageCourses, IsCourseInstructor, IsEnrolledStudent, IsStudentOwner
from LMS.api import api_error, api_success
from .tasks import process_scorm_upload_task

# Safe cache helpers: catch connection errors and fallback to no-cache
def cache_get_safe(key):
    try:
        return cache.get(key)
    except Exception:
        return None


def cache_set_safe(key, value, timeout=None):
    try:
        return cache.set(key, value, timeout=timeout)
    except Exception:
        return None


def cache_delete_safe(key):
    try:
        return cache.delete(key)
    except Exception:
        return None


def cache_delete_many_safe(keys):
    try:
        return cache.delete_many(keys)
    except Exception:
        for k in keys:
            try:
                cache.delete(k)
            except Exception:
                pass
        return None


class CategoryViewSet(viewsets.ModelViewSet):
    """ViewSet for course categories"""
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), CanManageCourses()]
        return [permissions.AllowAny()]

    def list(self, request, *args, **kwargs):
        cache_key = 'categories:list'
        data = cache_get_safe(cache_key)
        if data is None:
            queryset = self.filter_queryset(self.get_queryset())
            serializer = self.get_serializer(queryset, many=True)
            data = serializer.data
            cache_set_safe(cache_key, data, timeout=settings.CACHES['default'].get('TIMEOUT', 300))
        return api_success(data=data)


class CourseViewSet(viewsets.ModelViewSet):
    """ViewSet for courses"""
    queryset = Course.objects.all()
    
    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return CourseCreateSerializer
        if self.action == 'list':
            return CourseListSerializer
        return CourseSerializer
    
    def list(self, request, *args, **kwargs):
        user = request.user

        # Choose cache key based on role
        if not user.is_authenticated or user.role == 'student':
            cache_key = 'courses:list:public'
        elif user.role == 'super_admin' or user.role == 'admin':
            cache_key = 'courses:list:admin'
        elif user.role == 'staff':
            cache_key = 'courses:list:staff'
        elif user.role == 'tutor':
            cache_key = f'courses:list:tutor:{user.id}'
        else:
            cache_key = 'courses:list:public'

        data = cache_get_safe(cache_key)
        if data is None:
            queryset = self.filter_queryset(self.get_queryset())
            serializer = self.get_serializer(queryset, many=True)
            data = serializer.data
            cache_set_safe(cache_key, data, timeout=settings.CACHES['default'].get('TIMEOUT', 300))

        return api_success(data=data)

    def _invalidate_course_list_cache(self, course: Course | None = None):
        keys = ['courses:list:public', 'categories:list', 'courses:list:admin', 'courses:list:staff']
        if course and course.instructor:
            keys.append(f'courses:list:tutor:{course.instructor.id}')
        cache_delete_many_safe(keys)
    
    def get_permissions(self):
        if self.action in ['create']:
            return [permissions.IsAuthenticated(), CanManageCourses()]
        elif self.action in ['update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), IsCourseInstructor()]
        elif self.action == 'list':
            return [permissions.AllowAny()]  # Anyone can see courses
        return [permissions.AllowAny()]
    
    def get_queryset(self):
        user = self.request.user
        base_queryset = Course.objects.select_related(
            'category',
            'instructor',
            'instructor__tutor_profile',
            'created_by',
        )
        
        # If authenticated and admin/staff, show all
        if user.is_authenticated and user.role in ['admin', 'staff']:
            queryset = base_queryset
        
        # If tutor, show their courses
        elif user.is_authenticated and user.role == 'tutor':
            queryset = base_queryset.filter(instructor=user)
        
        # If student, show published courses
        else:
            queryset = base_queryset.filter(status='published')

        if self.action == 'retrieve':
            return queryset.prefetch_related('modules__contents', 'assessments')

        if self.action == 'list':
            return queryset

        return queryset
    
    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """Publish a course"""
        course = self.get_object()
        
        if not request.user.role in ['admin', 'staff'] and course.instructor != request.user:
            return api_error(message='Only admin or course instructor can publish', status_code=status.HTTP_403_FORBIDDEN)
        
        course.publish()
        # Invalidate caches
        try:
            self._invalidate_course_list_cache(course)
        except Exception:
            pass
        return api_success(message='Course published successfully')
    
    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        """Archive a course"""
        course = self.get_object()
        if not request.user.role in ['admin', 'staff'] and course.instructor != request.user:
            return api_error(message='Only admin or course instructor can archive', status_code=status.HTTP_403_FORBIDDEN)
        course.archive()
        try:
            self._invalidate_course_list_cache(course)
        except Exception:
            pass
        return api_success(message='Course archived')

    @action(detail=True, methods=['post'], url_path='upload-scorm')
    def upload_scorm(self, request, pk=None):
        """Upload a SCORM zip and start an import job (instructor or admin only)."""
        course = self.get_object()

        if not (request.user.role in ['admin', 'staff'] or course.instructor == request.user):
            return api_error(message='Only admin or course instructor can upload', status_code=403)

        # Lazy import to avoid requiring SCORM SDK on module import
        from .serializers import ScormUploadSerializer
        from .services import upload_scorm_zip

        serializer = ScormUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        scorm_zip = serializer.validated_data['scorm_zip']
        temp_path = None

        try:
            with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_file:
                for chunk in scorm_zip.chunks():
                    temp_file.write(chunk)
                temp_path = temp_file.name

            task = process_scorm_upload_task.delay(course.id, temp_path)
            course.scorm_import_job_id = f'celery:{task.id}'
            course.save(update_fields=['scorm_import_job_id'])

            return api_success(
                data={
                    'task_id': task.id,
                    'status': 'queued',
                },
                message='SCORM upload queued'
            )
        except Exception:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

            try:
                scorm_course_id, import_job_id = upload_scorm_zip(course, scorm_zip)
            except Exception as exc:
                return api_error(message='SCORM upload failed', errors=str(exc), status_code=400)

            course.is_scorm = True
            course.scorm_course_id = scorm_course_id
            course.scorm_import_job_id = import_job_id
            course.save(update_fields=['is_scorm', 'scorm_course_id', 'scorm_import_job_id'])

            return api_success(
                data={
                    'scorm_course_id': scorm_course_id,
                    'import_job_id': import_job_id,
                    'status': 'started',
                },
                message='SCORM upload started'
            )

    @action(detail=True, methods=['get'], url_path='scorm-status')
    def scorm_status(self, request, pk=None):
        course = self.get_object()

        if not course.scorm_import_job_id:
            return api_error(message='SCORM import job not found', status_code=404)

        if course.scorm_import_job_id.startswith('celery:'):
            task_id = course.scorm_import_job_id.split(':', 1)[1]
            async_result = AsyncResult(task_id)

            if async_result.state in {'PENDING', 'STARTED', 'RETRY'}:
                return api_success(data={'task_id': task_id, 'state': async_result.state})

            if async_result.state == 'FAILURE':
                return api_error(
                    message='SCORM upload task failed',
                    errors=str(async_result.result),
                    status_code=400,
                )

            course.refresh_from_db(fields=['scorm_import_job_id', 'scorm_course_id', 'is_scorm'])
            if course.scorm_import_job_id.startswith('celery:'):
                return api_success(data={'task_id': task_id, 'state': async_result.state})

        try:
            # Lazy import SCORM status helper
            from .services import get_import_job_status
            status = get_import_job_status(course.scorm_import_job_id)
        except Exception as exc:
            return api_error(message='SCORM status check failed', errors=str(exc), status_code=400)

        return api_success(data=status)

    @action(detail=True, methods=['get'], url_path='scorm-progress')
    def scorm_progress(self, request, pk=None):
        course = self.get_object()

        if not course.is_scorm:
            return api_error(message='Course is not a SCORM course', status_code=400)

        if not request.user.is_authenticated or request.user.role != 'student':
            return api_error(message='Only enrolled students can view progress', status_code=403)

        enrollment = CourseEnrollment.objects.filter(course=course, student=request.user).first()
        if not enrollment:
            return api_error(message='Enrollment not found', status_code=404)

        if not enrollment.scorm_registration_id:
            return api_error(message='SCORM registration not found', status_code=404)

        try:
            # Lazy import so missing SCORM SDK does not break module import.
            from .services import get_scorm_registration_progress

            progress = get_scorm_registration_progress(enrollment.scorm_registration_id)
        except Exception as exc:
            return api_error(message='SCORM progress check failed', errors=str(exc), status_code=400)

        completion_state = str(progress.get('completion') or '').strip().lower()
        is_completed_state = completion_state in {'complete', 'completed', 'passed'}
        tracked_seconds_raw = progress.get('total_seconds_tracked')

        try:
            tracked_seconds = float(tracked_seconds_raw or 0)
        except (TypeError, ValueError):
            tracked_seconds = 0

        completion_amount = progress.get('completion_amount')
        normalized_completion = None
        if completion_amount is not None:
            try:
                normalized_completion = float(completion_amount)
                if normalized_completion <= 1:
                    normalized_completion = normalized_completion * 100
                normalized_completion = max(0, min(100, normalized_completion))
            except (TypeError, ValueError):
                normalized_completion = None

        effective_progress = normalized_completion
        if effective_progress is None and is_completed_state:
            effective_progress = 100

        # Temporary UX fallback: when SCORM tracks time but reports no progress,
        # show a minimal in-progress value instead of 0%.
        if (
            (effective_progress is None or effective_progress <= 0)
            and tracked_seconds > 0
            and not is_completed_state
        ):
            effective_progress = 5

        if effective_progress is not None:
            effective_progress = max(float(enrollment.progress_percentage or 0), float(effective_progress))
            enrollment.progress_percentage = effective_progress
            if effective_progress >= 100:
                enrollment.status = 'completed'
                enrollment.completed_at = timezone.now()
            enrollment.save(update_fields=['progress_percentage', 'status', 'completed_at'])
            progress['completion_amount'] = effective_progress
            progress['display_progress_percentage'] = effective_progress

        return api_success(data=progress)
    
    
    @action(detail=True, methods=['post'], url_path='upload-thumbnail')
    def upload_thumbnail(self, request, pk=None):
        """Upload a thumbnail image for the course (instructor or admin only)"""
        course = self.get_object()
        
        # Permission check (reuse existing logic)
        if not (request.user.role in ['admin', 'staff'] or course.instructor == request.user):
            return api_error(message='Only admin or course instructor can upload', status_code=403)
        
        if 'thumbnail' not in request.FILES:
            return api_error(message='No thumbnail file provided', status_code=400)
        
        file = request.FILES['thumbnail']
        
        # Upload to Cloudinary
        result = upload(
            file,
            folder='course_thumbnails',
            public_id=f'course_{course.id}_thumb',
            overwrite=True
        )
        
        # Save the Cloudinary URL to the course model
        course.thumbnail = result['secure_url']
        course.save()
        
        return api_success(
            data={'url': result['secure_url']},
            message='Thumbnail uploaded successfully'
        )

    @action(detail=True, methods=['post'], url_path='upload-preview-video')
    def upload_preview_video(self, request, pk=None):
        """Upload a preview video for the course (instructor or admin only)"""
        course = self.get_object()
        
        if not (request.user.role in ['admin', 'staff'] or course.instructor == request.user):
            return api_error(message='Only admin or course instructor can upload', status_code=403)
        
        if 'video' not in request.FILES:
            return api_error(message='No video file provided', status_code=400)
        
        file = request.FILES['video']
        
        # Upload to Cloudinary (video type)
        result = upload(
            file,
            folder='course_previews',
            public_id=f'course_{course.id}_preview',
            resource_type='video',
            overwrite=True
        )
        
        course.preview_video = result['secure_url']
        course.save()
        
        return api_success(
            data={'url': result['secure_url']},
            message='Preview video uploaded successfully'
        )


class CourseModuleViewSet(viewsets.ModelViewSet):
    """ViewSet for course modules"""
    serializer_class = CourseModuleSerializer
    permission_classes = [permissions.IsAuthenticated, IsCourseInstructor]
    
    def get_queryset(self):
        course_id = self.kwargs.get('course_pk')
        return CourseModule.objects.filter(course_id=course_id)
    
    def perform_create(self, serializer):
        course_id = self.kwargs.get('course_pk')
        course = get_object_or_404(Course, id=course_id)
        serializer.save(course=course)


class ModuleContentViewSet(viewsets.ModelViewSet):
    """ViewSet for module content"""
    serializer_class = ModuleContentSerializer
    permission_classes = [permissions.IsAuthenticated, IsCourseInstructor]
    
    def get_queryset(self):
        module_id = self.kwargs.get('module_pk')
        return ModuleContent.objects.filter(module_id=module_id)
    
    def perform_create(self, serializer):
        module_id = self.kwargs.get('module_pk')
        module = get_object_or_404(CourseModule, id=module_id)
        serializer.save(module=module)


class CourseResourceViewSet(viewsets.ModelViewSet):
    """ViewSet for course-level resources"""

    serializer_class = CourseResourceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        course_id = self.kwargs.get('course_pk')
        qs = CourseResource.objects.filter(course_id=course_id)
        user = self.request.user

        if user.role == 'admin':
            return qs

        if user.role == 'staff':
            staff_profile = getattr(user, 'staff_profile', None)
            if staff_profile and getattr(staff_profile, 'permissions', None) and staff_profile.permissions.can_manage_courses:
                return qs
            return qs.none()

        if user.role == 'tutor':
            return qs.filter(course__instructor=user)

        if user.role == 'student':
            return qs.filter(course__enrollments__student=user).distinct()

        return qs.none()

    def perform_create(self, serializer):
        course_id = self.kwargs.get('course_pk')
        course = get_object_or_404(Course, id=course_id)
        user = self.request.user

        if user.role == 'tutor' and course.instructor != user:
            raise serializers.ValidationError('Only the course instructor can add resources')

        if user.role == 'staff':
            staff_profile = getattr(user, 'staff_profile', None)
            if not staff_profile or not getattr(staff_profile, 'permissions', None) or not staff_profile.permissions.can_manage_courses:
                raise serializers.ValidationError('You do not have permission to add resources')

        if user.role not in ['admin', 'staff', 'tutor']:
            raise serializers.ValidationError('Only instructors can add resources')

        serializer.save(course=course)


class AssessmentViewSet(viewsets.ModelViewSet):
    """ViewSet for assessments"""
    serializer_class = AssessmentSerializer
    
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), CanManageCourses()]
        return [permissions.IsAuthenticated()]
    
    def get_queryset(self):
        course_id = self.kwargs.get('course_pk')
        return Assessment.objects.filter(course_id=course_id)


class CourseEnrollmentViewSet(viewsets.ModelViewSet):
    """ViewSet for course enrollments"""
    serializer_class = CourseEnrollmentSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        
        # Admin sees all enrollments
        if user.role == 'admin':
            return CourseEnrollment.objects.all()
        
        # Tutor sees enrollments for their courses
        if user.role == 'tutor':
            return CourseEnrollment.objects.filter(course__instructor=user)
        
        # Students see their own enrollments
        return CourseEnrollment.objects.filter(student=user)
    
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return api_success(data=serializer.data)
    
    def perform_create(self, serializer):
        student = self.request.user
        if student.role != 'student':
            raise serializers.ValidationError('Only students can enroll in courses')
        course_id = self.request.data.get('course')
        course = get_object_or_404(Course, id=course_id)
        
        # Check if already enrolled
        if CourseEnrollment.objects.filter(student=student, course=course).exists():
            raise serializers.ValidationError("Already enrolled in this course")
        
        # Check course capacity
        if course.enrolled_count >= course.max_students:
            raise serializers.ValidationError("Course is full")
        
        # Enroll student
        enrollment = serializer.save(
            student=student,
            total_modules_at_enrollment=course.total_modules
        )
        
        # Update course enrollment count
        course.enrolled_count = CourseEnrollment.objects.filter(
            course=course, status='active'
        ).count()
        course.save()
        
        # Create module progress records
        for module in course.modules.all():
            StudentModuleProgress.objects.create(
                enrollment=enrollment,
                module=module
            )

        # Invalidate student-specific caches
        try:
            cache.delete(f'student:dashboard:{student.id}')
            cache.delete(f'student:enrollments:{student.id}')
        except Exception:
            pass

        return enrollment
    
    @action(detail=True, methods=['post'])
    def complete_module(self, request, pk=None):
        """Mark a module as completed"""
        enrollment = self.get_object()
        module_id = request.data.get('module_id')
        
        if not module_id:
            return api_error(message='module_id required', status_code=status.HTTP_400_BAD_REQUEST)
        
        module_progress = get_object_or_404(
            StudentModuleProgress,
            enrollment=enrollment,
            module_id=module_id
        )
        
        module_progress.is_completed = True
        module_progress.completed_at = timezone.now()
        module_progress.save()
        
        # Update enrollment progress
        enrollment.completed_modules = StudentModuleProgress.objects.filter(
            enrollment=enrollment, is_completed=True
        ).count()
        enrollment.update_progress()
        
        try:
            cache.delete(f'student:dashboard:{enrollment.student.id}')
            cache.delete(f'student:enrollments:{enrollment.student.id}')
        except Exception:
            pass

        return api_success(data={'progress': enrollment.progress_percentage}, message='Module completed')
    
    @action(detail=True, methods=['post'])
    def complete_content(self, request, pk=None):
        """Mark a content item as completed"""
        enrollment = self.get_object()
        content_id = request.data.get('content_id')
        
        if not content_id:
            return api_error(message='content_id required', status_code=status.HTTP_400_BAD_REQUEST)
        
        content_progress, created = StudentContentProgress.objects.get_or_create(
            enrollment=enrollment,
            content_id=content_id,
            defaults={'is_completed': True, 'completed_at': timezone.now()}
        )
        
        if not created:
            content_progress.is_completed = True
            content_progress.completed_at = timezone.now()
            content_progress.save()

        module = content_progress.content.module
        module_contents = ModuleContent.objects.filter(module=module)
        if module_contents.exists():
            completed_count = StudentContentProgress.objects.filter(
                enrollment=enrollment,
                content__module=module,
                is_completed=True
            ).count()

            if completed_count == module_contents.count():
                module_progress, _ = StudentModuleProgress.objects.get_or_create(
                    enrollment=enrollment,
                    module=module,
                    defaults={'is_completed': True, 'completed_at': timezone.now()}
                )
                if not module_progress.is_completed:
                    module_progress.is_completed = True
                    module_progress.completed_at = timezone.now()
                    module_progress.save()

                enrollment.completed_modules = StudentModuleProgress.objects.filter(
                    enrollment=enrollment,
                    is_completed=True
                ).count()
                enrollment.update_progress()
        
        try:
            cache.delete(f'student:dashboard:{enrollment.student.id}')
            cache.delete(f'student:enrollments:{enrollment.student.id}')
        except Exception:
            pass

        return api_success(message='Content completed')


class StudentCoursesAPIView(APIView):
    """Student-facing list of published courses"""
    permission_classes = [permissions.IsAuthenticated, IsEnrolledStudent]

    def get(self, request):
        courses = Course.objects.filter(status='published').select_related('category', 'instructor')
        serializer = CourseListSerializer(courses, many=True)
        return api_success(data=serializer.data)


class StudentCourseDetailAPIView(APIView):
    """Student-facing course detail with modules and contents"""
    permission_classes = [permissions.IsAuthenticated, IsEnrolledStudent]

    def get(self, request, course_id):
        course = get_object_or_404(
            Course.objects.select_related('category', 'instructor').prefetch_related('modules__contents', 'assessments'),
            id=course_id
        )

        if course.status != 'published' and not CourseEnrollment.objects.filter(course=course, student=request.user).exists():
            return api_error(message='Course not available', status_code=status.HTTP_403_FORBIDDEN)

        serializer = CourseSerializer(course)
        data = serializer.data

        if course.is_scorm and CourseEnrollment.objects.filter(course=course, student=request.user).exists():
            enrollment = CourseEnrollment.objects.get(course=course, student=request.user)
            try:
                # Lazy import SCORM launch helper
                from .services import get_scorm_launch_link

                registration_id, launch_link = get_scorm_launch_link(
                    course,
                    request.user,
                    enrollment.scorm_registration_id,
                )
                if enrollment.scorm_registration_id != registration_id:
                    enrollment.scorm_registration_id = registration_id
                    enrollment.save(update_fields=['scorm_registration_id'])
                data['scorm_launch_url'] = launch_link
            except Exception as exc:
                data['scorm_launch_error'] = str(exc)

        return api_success(data=data)


class StudentEnrolledCoursesAPIView(APIView):
    """Student-facing list of enrollments with course info"""
    permission_classes = [permissions.IsAuthenticated, IsEnrolledStudent]

    def get(self, request):
        cache_key = f'student:enrollments:{request.user.id}'
        data = cache_get_safe(cache_key)
        if data is not None:
            return api_success(data=data)

        enrollments = (
            CourseEnrollment.objects
            .filter(student=request.user)
            .select_related('course', 'course__category', 'course__instructor')
        )
        serializer = EnrollmentWithCourseSerializer(enrollments, many=True)
        cache_set_safe(cache_key, serializer.data, timeout=settings.CACHES['default'].get('TIMEOUT', 300))

        return api_success(data=serializer.data)


class StudentCourseEnrollAPIView(APIView):
    """Enroll the current student in a published course"""
    permission_classes = [permissions.IsAuthenticated, IsEnrolledStudent]

    def post(self, request, course_id):
        course = get_object_or_404(Course, id=course_id, status='published')

        if CourseEnrollment.objects.filter(student=request.user, course=course).exists():
            return api_error(message='Already enrolled in this course', status_code=status.HTTP_400_BAD_REQUEST)

        if course.enrolled_count >= course.max_students:
            return api_error(message='Course is full', status_code=status.HTTP_400_BAD_REQUEST)

        enrollment = CourseEnrollment.objects.create(
            student=request.user,
            course=course,
            total_modules_at_enrollment=course.total_modules,
        )

        course.enrolled_count = CourseEnrollment.objects.filter(course=course, status='active').count()
        course.save()

        for module in course.modules.all():
            StudentModuleProgress.objects.create(
                enrollment=enrollment,
                module=module,
            )

        serializer = EnrollmentWithCourseSerializer(enrollment)
        return api_success(data=serializer.data, message='Enrolled successfully', status_code=status.HTTP_201_CREATED)


class StudentDashboardAPIView(APIView):
    """Student dashboard summary data"""
    permission_classes = [permissions.IsAuthenticated, IsEnrolledStudent]

    def get(self, request):
        student = request.user
        cache_key = f'student:dashboard:{student.id}'
        data = cache_get_safe(cache_key)
        if data is not None:
            return api_success(data=data)

        enrollments = CourseEnrollment.objects.filter(student=student)
        total_courses = enrollments.count()

        avg_score = (
            StudentAssessment.objects.filter(student=student)
            .aggregate(avg=db_models.Avg('score'))
            .get('avg')
        ) or 0

        total_badges = Certificate.objects.filter(student=student).count()

        completed_modules = StudentModuleProgress.objects.filter(
            enrollment__student=student, is_completed=True
        ).count()
        credits_xp = completed_modules * 100

        # Study time totals
        study_minutes = (
            StudentContentProgress.objects.filter(enrollment__student=student)
            .aggregate(total=db_models.Sum('time_spent_minutes'))
            .get('total')
        ) or 0
        study_hours = round(study_minutes / 60, 1) if study_minutes else 0

        # Activity data for last 7 days
        start_date = timezone.now().date() - timedelta(days=6)
        activity_qs = (
            StudentContentProgress.objects.filter(
                enrollment__student=student,
                updated_at__date__gte=start_date
            )
            .annotate(day=TruncDate('updated_at'))
            .values('day')
            .annotate(total=db_models.Sum('time_spent_minutes'))
        )
        activity_map = {
            entry['day']: entry['total'] or 0 for entry in activity_qs
        }
        activity_data = []
        for i in range(7):
            day = start_date + timedelta(days=i)
            minutes = activity_map.get(day, 0)
            activity_data.append({
                'name': day.strftime('%a'),
                'hours': round(minutes / 60, 1) if minutes else 0,
            })

        # Ongoing courses with next lesson
        ongoing_courses = []
        active_enrollments = (
            enrollments
            .filter(status='active')
            .select_related('course')
            .prefetch_related('course__modules__contents')
            .order_by('-last_accessed_at')[:4]
        )
        for enrollment in active_enrollments:
            course = enrollment.course
            next_lesson = None
            modules = list(course.modules.all().order_by('order_number'))
            if modules:
                first_module = modules[0]
                first_content = first_module.contents.all().order_by('order_number').first()
                next_lesson = first_content.title if first_content else first_module.title

            ongoing_courses.append({
                'id': course.id,
                'title': course.title,
                'progress': float(enrollment.progress_percentage or 0),
                'next_lesson': next_lesson or 'No content yet',
            })

        recent_badges = [
            {
                'id': cert.id,
                'name': cert.course.title,
                'date': cert.issued_at,
            }
            for cert in Certificate.objects.filter(student=student).order_by('-issued_at')[:3]
        ]

        data = {
            'stats': {
                'total_courses': total_courses,
                'total_badges': total_badges,
                'avg_score': round(float(avg_score), 2) if avg_score else 0,
                'study_hours': f"{study_hours}h",
                'credits_xp': credits_xp,
            },
            'activity_data': activity_data,
            'recent_badges': recent_badges,
            'ongoing_courses': ongoing_courses,
            'notice': None,
            'job_matches_count': 0,
        }

        cache_set_safe(cache_key, data, timeout=settings.CACHES['default'].get('TIMEOUT', 300))
        return api_success(data=data)


class StudentAssessmentViewSet(viewsets.ModelViewSet):
    """ViewSet for student assessments"""
    serializer_class = StudentAssessmentSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin':
            return StudentAssessment.objects.all()
        return StudentAssessment.objects.filter(student=user)
    
    def perform_create(self, serializer):
        assessment_id = self.request.data.get('assessment')
        assessment = get_object_or_404(Assessment, id=assessment_id)
        
        score = self.request.data.get('score', 0)
        passed = score >= assessment.passing_score
        
        serializer.save(
            student=self.request.user,
            assessment=assessment,
            passed=passed
        )


class CertificateViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for certificates (read-only)"""
    serializer_class = CertificateSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin':
            return Certificate.objects.all()
        if user.role == 'tutor':
            return Certificate.objects.filter(course__instructor=user)
        return Certificate.objects.filter(student=user)
    
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return api_success(data=serializer.data)
    
    @action(detail=False, methods=['post'])
    def generate_certificate(self, request):
        """Generate certificate for completed course"""
        enrollment_id = request.data.get('enrollment_id')
        enrollment = get_object_or_404(CourseEnrollment, id=enrollment_id, student=request.user)
        
        if enrollment.status != 'completed':
            return api_error(message='Course not completed', status_code=status.HTTP_400_BAD_REQUEST)
        
        if hasattr(enrollment, 'certificate'):
            return api_success(data={'id': enrollment.certificate.id}, message='Certificate already issued')
        
        # Generate certificate (in real app, use PDF generation library)
        unique_code = f"CERT-{enrollment.course.id}-{request.user.id}-{timezone.now().strftime('%Y%m%d%H%M')}"
        certificate_url = f"https://yourdomain.com/certificates/{unique_code}.pdf"
        
        certificate = Certificate.objects.create(
            student=request.user,
            course=enrollment.course,
            enrollment=enrollment,
            unique_code=unique_code,
            certificate_url=certificate_url,
            final_score=enrollment.progress_percentage
        )
        
        enrollment.certificate_issued = True
        enrollment.certificate_url = certificate_url
        enrollment.save()
        
        return api_success(data=CertificateSerializer(certificate).data, message='Certificate generated')


class CourseReviewViewSet(viewsets.ModelViewSet):
    """ViewSet for course reviews"""
    serializer_class = CourseReviewSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        course_id = self.kwargs.get('course_pk')
        return CourseReview.objects.filter(course_id=course_id)
    
    def perform_create(self, serializer):
        course_id = self.kwargs.get('course_pk')
        serializer.save(
            student=self.request.user,
            course_id=course_id
        )


class CourseAnnouncementViewSet(viewsets.ModelViewSet):
    """ViewSet for course announcements"""
    serializer_class = CourseAnnouncementSerializer
    permission_classes = [permissions.IsAuthenticated, CanManageCourses]
    
    def get_queryset(self):
        course_id = self.kwargs.get('course_pk')
        return CourseAnnouncement.objects.filter(course_id=course_id)
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)