from rest_framework import viewsets, status, permissions
from rest_framework import serializers
from rest_framework.views import APIView, PermissionDenied
from rest_framework.response import Response
from rest_framework.decorators import action
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db import models as db_models
from cloudinary.uploader import upload
from django.db.models.functions import TruncDate
from datetime import timedelta
from django.db.models import Count, Q, Prefetch
from django.core.cache import cache
from .models import (
    Category, Course, CourseModule, ModuleContent, CourseEnrollment, CourseResource,
    StudentModuleProgress, StudentContentProgress,
    Assessment, StudentAssessment, Certificate,
    CourseReview, CourseAnnouncement, CoursePayment,
    LiveSession, Attendance, TutorNote
)
from .serializers import (
    AssessmentCreateSerializer, CategorySerializer, CourseResourceCreateSerializer, CourseSerializer, CourseCreateSerializer,
    CourseModuleSerializer, CourseModuleBasicSerializer,
    ModuleContentSerializer, AssessmentSerializer,
    CourseEnrollmentSerializer, StudentAssessmentSerializer,
    CertificateSerializer, CourseReviewSerializer,
    CourseAnnouncementSerializer, CourseListSerializer,
    EnrollmentWithCourseSerializer, ScormUploadSerializer,
    CourseResourceSerializer, CoursePaymentSerializer,
    LiveSessionSerializer, AttendanceSerializer, TutorNoteSerializer
)
import os
import json
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from .services import upload_scorm_zip, get_import_job_status, get_scorm_launch_link, get_scorm_registration_progress, upload_content_to_scorm, get_content_launch_link
from .permissions import CanManageCourses, IsCourseInstructor, IsEnrolledStudent, IsStudentOwner, CanManagePayments
from LMS.api import api_error, api_success


class CategoryViewSet(viewsets.ModelViewSet):
    """ViewSet for course categories"""
    queryset = Category.objects.annotate(course_count=Count('courses'))
    serializer_class = CategorySerializer
    
    def list(self, request, *args, **kwargs):
        cache_key = 'all_categories'
        categories = cache.get(cache_key)
        if categories is None:
            queryset = self.filter_queryset(self.get_queryset())
            serializer = self.get_serializer(queryset, many=True)
            categories = serializer.data
            cache.set(cache_key, categories, 60 * 10)  # cache for 10 minutes
        return api_success(data=categories)
    
    # For create/update/delete, invalidate cache
    def perform_create(self, serializer):
        super().perform_create(serializer)
        cache.delete('all_categories')
    
    def perform_update(self, serializer):
        super().perform_update(serializer)
        cache.delete('all_categories')
    
    def perform_destroy(self, instance):
        super().perform_destroy(instance)
        cache.delete('all_categories')
    
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), CanManageCourses()]
        return [permissions.AllowAny()]


class CourseViewSet(viewsets.ModelViewSet):
    """ViewSet for courses"""
    queryset = Course.objects.all()
    
    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return CourseCreateSerializer
        if self.action == 'list':
            # Use lightweight serializer for listing
            return CourseListSerializer
        return CourseSerializer
    
    def get_queryset(self):
        user = self.request.user
        base_qs = Course.objects.select_related(
            'category', 'instructor__tutor_profile', 'created_by'
        )
        
        # Handle soft-deleted courses
        include_deleted = self.request.query_params.get('include_deleted', 'false').lower() == 'true'
        is_admin_role = user.is_authenticated and (user.is_super_admin or user.role in ['admin', 'super_admin', 'staff'])
        
        if self.action == 'deleted_courses':
            return base_qs.filter(is_deleted=True)
            
        if not (include_deleted and is_admin_role):
            base_qs = base_qs.filter(is_deleted=False)
            
        if self.action in ['retrieve', 'update', 'partial_update']:
            base_qs = base_qs.prefetch_related('modules__contents', 'assessments', 'modules', 'modules__resources')

        # Optional: annotate only if fields are used in the serializer
        if 'total_modules' in self.get_serializer().fields:
            base_qs = base_qs.annotate(
                total_modules_count=Count('modules', distinct=True),
                total_contents_count=Count('modules__contents', distinct=True),
                total_quizzes_count=Count('assessments', filter=Q(assessments__assessment_type='quiz'), distinct=True)
            )

        if user.is_authenticated and user.role in ['admin', 'super_admin', 'staff']:
            return base_qs
        if user.is_authenticated and user.role == 'tutor':
            return base_qs.filter(instructor=user)
        return base_qs.filter(status='published')
        
    def destroy(self, request, *args, **kwargs):
        """Override destroy to use soft delete for admin/super_admin"""
        instance = self.get_object()
        user = request.user
        
        if user.is_super_admin or user.role in ['super_admin', 'admin']:
            instance.is_deleted = True
            instance.deleted_at = timezone.now()
            instance.deleted_by = user
            instance.save()
            return api_success(message=f"Course '{instance.title}' soft-deleted successfully.")
        
        # For tutors, we might want to prevent permanent delete too
        if user.role == 'tutor' and instance.instructor == user:
            instance.is_deleted = True
            instance.deleted_at = timezone.now()
            instance.deleted_by = user
            instance.save()
            return api_success(message=f"Course '{instance.title}' has been moved to trash.")

        return super().destroy(request, *args, **kwargs)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        # Use pagination if you have many courses (add pagination class in settings)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return api_success(data=serializer.data)
    
    def get_permissions(self):
        if self.action in ['create']:
            return [permissions.IsAuthenticated(), CanManageCourses()]
        elif self.action in ['update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), IsCourseInstructor()]
        elif self.action == 'list':
            return [permissions.AllowAny()]  # Anyone can see courses
        return [permissions.AllowAny()]
    
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return api_success(data=serializer.data)
    
    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """Publish a course"""
        course = self.get_object()
        
        if not request.user.role in ['admin', 'super_admin', 'staff'] and course.instructor != request.user:
            return api_error(message='Only admin, super admin or course instructor can publish', status_code=status.HTTP_403_FORBIDDEN)
        
        course.publish()
        return api_success(message='Course published successfully')
    
    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        """Archive a course"""
        course = self.get_object()
        if not request.user.role in ['admin', 'super_admin', 'staff'] and course.instructor != request.user:
            return api_error(message='Only admin, super admin or course instructor can archive', status_code=status.HTTP_403_FORBIDDEN)
        course.archive()
        return api_success(message='Course archived')
    
    @action(detail=True, methods=['post'], url_path='restore')
    def restore(self, request, pk=None):
        """Restore a soft-deleted course"""
        # We need a special way to get the object because it's filtered out of the queryset
        try:
            course = Course.objects.get(pk=pk, is_deleted=True)
        except Course.DoesNotExist:
            return api_error(message='Course not found or not deleted.', status_code=status.HTTP_404_NOT_FOUND)
        
        user = request.user
        if not (user.is_super_admin or user.role in ['super_admin', 'admin']):
             return api_error(message='You do not have permission to restore courses.', status_code=status.HTTP_403_FORBIDDEN)
        
        course.is_deleted = False
        course.deleted_at = None
        course.deleted_by = None
        # Keep original status or reset to draft if it was published
        if course.status == 'published':
            course.status = 'draft'
        course.save()
        
        return api_success(message=f"Course '{course.title}' restored successfully.")

    @action(detail=False, methods=['get'], url_path='deleted')
    def deleted_courses(self, request):
        """List all soft-deleted courses (for admin/super_admin only)"""
        user = request.user
        if not (user.is_super_admin or user.role in ['super_admin', 'admin']):
            return api_error(message='Permission denied', status_code=status.HTTP_403_FORBIDDEN)
            
        queryset = self.get_queryset() # This will use the action='deleted_courses' logic in get_queryset
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return api_success(data=serializer.data)

    @action(detail=True, methods=['post'], url_path='upload-scorm')
    def upload_scorm(self, request, pk=None):
        """Upload a SCORM zip and queue async import job (instructor or admin only)."""
        import logging
        logger = logging.getLogger(__name__)
        
        course = self.get_object()

        if not (request.user.role in ['admin', 'staff'] or course.instructor == request.user):
            return api_error(message='Only admin or course instructor can upload', status_code=403)

        print(f"DEBUG: upload_scorm request.data keys: {request.data.keys()}")
        print(f"DEBUG: upload_scorm FILES keys: {request.FILES.keys()}")
        serializer = ScormUploadSerializer(data=request.data)
        if not serializer.is_valid():
            print(f"DEBUG: Serializer errors: {serializer.errors}")
            logger.error(f"Serializer errors: {serializer.errors}")
        serializer.is_valid(raise_exception=True)

        scorm_zip = serializer.validated_data['scorm_zip']

        # Mark course as SCORM FIRST, before queuing the task
        # We also clear scorm_import_job_id to ensure any old error status is reset
        course.is_scorm = True
        scorm_course_id = f"local_course_{course.id}"
        course.scorm_course_id = scorm_course_id
        course.scorm_import_job_id = None
        course.save(update_fields=['is_scorm', 'scorm_course_id', 'scorm_import_job_id'])
        logger.info(f"Course {course.id} marked as SCORM with scorm_course_id={scorm_course_id} (cleared old job ID)")
        print(f"DEBUG: Course saved with is_scorm=True, scorm_course_id={scorm_course_id}, cleared scorm_import_job_id")

        celery_task_id = None
        try:
            scorm_course_id, celery_task_id = upload_scorm_zip(course, scorm_zip)
            logger.info(f"SCORM upload task queued with task_id={celery_task_id}")
            print(f"DEBUG: SCORM upload queued with task_id={celery_task_id}")
        except Exception as exc:
            logger.error(f"SCORM upload task queueing failed: {str(exc)}", exc_info=True)
            print(f"DEBUG: SCORM upload task failed: {str(exc)}")
            # Don't fail the response - course is already marked as SCORM
            # Task will run later or manual sync can be done
            celery_task_id = None

        return api_success(
            data={
                'scorm_course_id': scorm_course_id,
                'task_id': celery_task_id,
                'is_scorm': True,
                'message': 'SCORM course created. Upload processing in background...'
            },
            message='SCORM upload started'
        )

    @action(detail=True, methods=['get'], url_path='scorm-status')
    def scorm_status(self, request, pk=None):
        """Check SCORM upload and import status."""
        course = self.get_object()

        if not course.is_scorm:
            return api_error(message='Course is not marked as SCORM', status_code=400)

        # If import job ID not set yet, the upload task is still running
        if not course.scorm_import_job_id:
            return api_success(
                data={
                    'status': 'uploading',
                    'message': 'SCORM package is still being uploaded to SCORM Cloud',
                    'job_id': None
                }
            )

        try:
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
            # Instead of 404, return 0 progress to avoid frontend console errors
            return api_success(data={
                'registration_id': None,
                'completion': 'NOT_STARTED',
                'completion_amount': 0,
                'message': 'SCORM registration not yet initialized'
            })

        try:
            progress = get_scorm_registration_progress(enrollment.scorm_registration_id)
            
            completion_amount = progress.get('completion_amount')
            completion_status = progress.get('completion')
            total_seconds = progress.get('total_seconds_tracked', 0) or 0
            
            # If explicitly marked COMPLETED, force 100 even if amount is 0
            if completion_status == 'COMPLETED' or progress.get('success') == 'PASSED':
                completion_amount = 100.0
            elif completion_amount is not None:
                if completion_amount <= 1:
                    completion_amount = completion_amount * 100
                
                # Nudge: If they have tracked time but 0% progress (common in SCORM 1.2),
                # show 1% so they know it's working
                if completion_amount < 1 and total_seconds > 5:
                    completion_amount = 1.0
                    
                completion_amount = max(0, min(100, float(completion_amount)))
            
            if completion_amount is not None:
                enrollment.progress_percentage = completion_amount
                if completion_amount >= 100:
                    enrollment.status = 'completed'
                    if not enrollment.completed_at:
                        enrollment.completed_at = timezone.now()
                enrollment.save(update_fields=['progress_percentage', 'status', 'completed_at'])
                progress['completion_amount'] = completion_amount
                
                # Broadcast update via WebSocket
                CourseEnrollmentViewSet.broadcast_progress(enrollment.id)

            return api_success(data=progress)

        except Exception as exc:
            # Handle the case where the registration ID is invalid or course was deleted on SCORM Cloud
            error_msg = str(exc)
            if "Could not find registration" in error_msg:
                 return api_success(data={
                    'registration_id': enrollment.scorm_registration_id,
                    'completion': 'UNKNOWN',
                    'completion_amount': enrollment.progress_percentage,
                    'error': 'Registration not found on SCORM Cloud'
                })
            return api_error(message='SCORM progress check failed', errors=error_msg, status_code=400)
    
    
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
        return CourseModule.objects.filter(course_id=course_id).prefetch_related('contents')
    
    def perform_create(self, serializer):
        course_id = self.kwargs.get('course_pk')
        course = get_object_or_404(Course, id=course_id)
        serializer.save(course=course)


class ModuleContentViewSet(viewsets.ModelViewSet):
    """ViewSet for module content"""
    serializer_class = ModuleContentSerializer
    
    def get_permissions(self):
        if self.action in ['launch', 'scorm_status', 'retrieve', 'list']:
            # For these actions, we allow both instructors and enrolled students
            return [permissions.IsAuthenticated()]
        # For sensitive actions like upload, only instructors
        return [permissions.IsAuthenticated(), IsCourseInstructor()]

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        
        # If the action is launch/scorm_status, we need to verify the user is either the instructor or an enrolled student
        if self.action in ['launch', 'scorm_status', 'retrieve', 'list']:
            user = request.user
            if user.role == 'admin':
                return
                
            course = obj.module.course
            if course.instructor == user:
                return
                
            if user.role == 'student':
                from .models import CourseEnrollment, CoursePayment
                if CourseEnrollment.objects.filter(course=course, student=user, status='active').exists():
                    # Safety Check: If course is paid, ensure confirmed payment exists
                    if not course.is_free and course.price > 0:
                        if not CoursePayment.objects.filter(course=course, student=user, status='confirmed').exists():
                            self.permission_denied(request, message="Payment verification required to access this content.")
                    return
            
            self.permission_denied(request, message="You do not have permission to access this content.")
    
    def get_queryset(self):
        module_id = self.kwargs.get('module_pk')
        return ModuleContent.objects.filter(module_id=module_id)
    
    def perform_create(self, serializer):
        module_id = self.kwargs.get('module_pk')
        module = get_object_or_404(CourseModule, id=module_id)
        serializer.save(module=module)

    @action(detail=True, methods=['post'], url_path='upload-to-scorm')
    def upload_to_scorm(self, request, pk=None, course_pk=None, module_pk=None):
        """Upload a PDF, MP4, or MP3 file to SCORM Cloud for this content item."""
        content = self.get_object()
        
        if 'file' not in request.FILES:
            return api_error(message='No file provided', status_code=400)
        
        uploaded_file = request.FILES['file']
        
        # Validate file extension
        _, ext = os.path.splitext(uploaded_file.name)
        allowed_exts = ['.pdf', '.mp4', '.mp3']
        if ext.lower() not in allowed_exts:
            return api_error(message=f'Invalid file type. Allowed: {", ".join(allowed_exts)}', status_code=400)
        
        try:
            # If it's a re-upload, we might want to create a new version
            may_create_new_version = content.scorm_course_id is not None
            
            scorm_course_id, import_job_id = upload_content_to_scorm(
                content, 
                uploaded_file, 
                may_create_new_version=may_create_new_version
            )
            
            content.scorm_course_id = scorm_course_id
            content.scorm_import_job_id = import_job_id
            content.scorm_status = 'processing'
            if may_create_new_version:
                content.scorm_version += 1
            content.save()
            
            return api_success(
                data={
                    'scorm_course_id': scorm_course_id,
                    'import_job_id': import_job_id,
                    'version': content.scorm_version
                },
                message='Upload to SCORM Cloud started'
            )
        except Exception as e:
            return api_error(message=f'SCORM Cloud upload failed: {str(e)}', status_code=500)

    @action(detail=True, methods=['get'], url_path='scorm-status')
    def scorm_status(self, request, pk=None, course_pk=None, module_pk=None):
        """Check the status of a SCORM Cloud import job for this content item."""
        content = self.get_object()
        
        if not content.scorm_import_job_id:
            return api_error(message='No SCORM Cloud import job found for this content', status_code=404)
        
        try:
            status_data = get_import_job_status(content.scorm_import_job_id)
            
            # Update local status if it's finished or complete
            status_lower = status_data['status'].lower()
            if status_lower in ['finished', 'complete']:
                content.scorm_status = 'finished'
                content.save()
            elif status_lower == 'error':
                content.scorm_status = 'failed'
                content.save()
                
            return api_success(data=status_data)
        except Exception as e:
            return api_error(message=f'Failed to check SCORM status: {str(e)}', status_code=500)

    @action(detail=True, methods=['get'], url_path='launch')
    def launch(self, request, pk=None, course_pk=None, module_pk=None):
        """Get a SCORM Cloud launch link for this content item."""
        content = self.get_object()
        
        if not content.scorm_course_id or content.scorm_status != 'finished':
            return api_error(message='Content is not ready on SCORM Cloud', status_code=400)
        
        try:
            registration_id, launch_url = get_content_launch_link(content, request.user, course_pk)
            return api_success(data={'launch_url': launch_url, 'registration_id': registration_id})
        except Exception as e:
            return api_error(message=f'Failed to generate launch link: {str(e)}', status_code=500)


class CourseResourceViewSet(viewsets.ModelViewSet):
    """ViewSet for course resources - supports module attachment and file upload"""
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return CourseResourceCreateSerializer
        return CourseResourceSerializer

    def get_queryset(self):
        course_id = self.kwargs.get('course_pk')
        qs = CourseResource.objects.filter(course_id=course_id).select_related('module')
        user = self.request.user

        # Admin sees all
        if user.role == 'admin':
            return qs

        # Staff with permission
        if user.role == 'staff':
            staff_profile = getattr(user, 'staff_profile', None)
            if staff_profile and getattr(staff_profile, 'permissions', None) and staff_profile.permissions.can_manage_courses:
                return qs
            return qs.none()

        # Tutor sees resources for their courses
        if user.role == 'tutor':
            return qs.filter(course__instructor=user)

        # Student sees resources for enrolled courses with confirmed payments (if paid)
        if user.role == 'student':
            from django.db.models import Q
            from .models import CoursePayment
            
            # Get IDs of courses student has confirmed payments for
            paid_course_ids = CoursePayment.objects.filter(
                student=user, 
                status='confirmed'
            ).values_list('course_id', flat=True)
            
            return qs.filter(
                course__enrollments__student=user,
                course__status='published'
            ).filter(
                Q(course__is_free=True) | Q(course__id__in=paid_course_ids)
            ).distinct()

        return qs.none()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        course_id = self.kwargs.get('course_pk')
        if course_id:
            context['course'] = get_object_or_404(Course, id=course_id)
        return context

    def perform_create(self, serializer):
        course_id = self.kwargs.get('course_pk')
        course = get_object_or_404(Course, id=course_id)
        user = self.request.user

        # Permission checks
        if user.role == 'tutor' and course.instructor != user:
            raise PermissionDenied('Only the course instructor can add resources')
        
        if user.role == 'staff':
            staff_profile = getattr(user, 'staff_profile', None)
            if not staff_profile or not getattr(staff_profile, 'permissions', None) or not staff_profile.permissions.can_manage_courses:
                raise PermissionDenied('You do not have permission to add resources')

        if user.role not in ['admin', 'staff', 'tutor']:
            raise PermissionDenied('Only instructors can add resources')

        # Pass course to serializer context
        serializer.context['course'] = course
        serializer.save()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        
        # Return with full serializer for response
        output_serializer = CourseResourceSerializer(serializer.instance)
        headers = self.get_success_headers(output_serializer.data)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = CourseResourceSerializer(queryset, many=True)
        return api_success(data=serializer.data)


class AssessmentViewSet(viewsets.ModelViewSet):
    """ViewSet for assessments - works both nested under courses and directly"""
    
    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return AssessmentCreateSerializer
        return AssessmentSerializer
    
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), CanManageCourses()]
        if self.action in ['list', 'retrieve']:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated()]
    
    def get_queryset(self):
        user = self.request.user
        course_pk = self.kwargs.get('course_pk')
        
        # If accessed via nested route (courses/{course_pk}/assessments/)
        if course_pk:
            if user.role == 'student':
                return Assessment.objects.filter(
                    course_id=course_pk,
                    course__enrollments__student=user,
                    course__status='published'
                ).distinct()
            return Assessment.objects.filter(course_id=course_pk)
        
        # Direct access (assessments/)
        if user.role in ['admin', 'staff']:
            return Assessment.objects.all()
        elif user.role == 'tutor':
            return Assessment.objects.filter(course__instructor=user)
        elif user.role == 'student':
            return Assessment.objects.filter(
                course__enrollments__student=user,
                course__status='published'
            ).distinct()
        elif user.role == 'company':
            return Assessment.objects.none()
        
        return Assessment.objects.none()
    
    def perform_create(self, serializer):
        course_pk = self.kwargs.get('course_pk')
        if course_pk:
            course = get_object_or_404(Course, id=course_pk)
            serializer.save(course=course)
        else:
            serializer.save()
    
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return api_success(data=serializer.data)
    
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return api_success(data=serializer.data)

class CourseEnrollmentViewSet(viewsets.ModelViewSet):
    """ViewSet for course enrollments"""
    serializer_class = CourseEnrollmentSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        
        base_qs = CourseEnrollment.objects.select_related('student', 'student__student_profile', 'course', 'course__category', 'course__instructor', 'course__instructor__tutor_profile')
        # Admin sees all enrollments
        if user.role == 'admin':
            return base_qs
        
        # Tutor sees enrollments for their courses
        if user.role == 'tutor':
            return base_qs.filter(course__instructor=user)
        
        # Students see their own enrollments
        return base_qs.filter(student=user)

    @action(detail=True, methods=['get'])
    def progress(self, request, pk=None):
        """Get current progress for this enrollment"""
        enrollment = self.get_object()
        return Response({
            "progress": float(enrollment.progress_percentage),
            "status": enrollment.status,
            "score": 0,
        })

    @action(detail=True, methods=['post'])
    def heartbeat(self, request, pk=None):
        """Receive progress heartbeat for a specific content (e.g. video playback)"""
        enrollment = self.get_object()
        content_id = request.data.get('content_id')
        current_time = request.data.get('current_time') # in seconds
        duration = request.data.get('duration') # in seconds
        
        if not content_id:
            return api_error(message='content_id is required')

        print(f"DEBUG: Heartbeat - enrollment_id: {enrollment.id}, content_id: {content_id}")
        content = get_object_or_404(ModuleContent, id=content_id)
        print(f"DEBUG: Heartbeat - Found content: {content.title} (ID: {content.id})")
        content_progress, created = StudentContentProgress.objects.get_or_create(
            enrollment=enrollment,
            content=content
        )
        print(f"DEBUG: Heartbeat - StudentContentProgress created: {created}")
        
        was_updated = False
        if current_time is not None:
            # Update time spent
            content_progress.time_spent_minutes = max(content_progress.time_spent_minutes, int(current_time / 60))
            
            # Auto-complete video if 90% watched
            if duration and duration > 0:
                completion_ratio = current_time / duration
                if completion_ratio >= 0.9 and not content_progress.is_completed:
                    content_progress.is_completed = True
                    content_progress.completed_at = timezone.now()
                    was_updated = True
            
            content_progress.save()

        # If content was marked completed, update module and enrollment
        if was_updated:
            module = content.module
            if module:
                all_contents = module.contents.all()
                completed_count = StudentContentProgress.objects.filter(
                    enrollment=enrollment,
                    content__in=all_contents,
                    is_completed=True
                ).count()
                
                if completed_count == all_contents.count():
                    module_progress, _ = StudentModuleProgress.objects.get_or_create(
                        enrollment=enrollment,
                        module=module
                    )
                    if not module_progress.is_completed:
                        module_progress.is_completed = True
                        module_progress.completed_at = timezone.now()
                        module_progress.save()
                        
                        enrollment.completed_modules = StudentModuleProgress.objects.filter(
                            enrollment=enrollment,
                            is_completed=True
                        ).count()

        # Always update progress (e.g. for the 1% 'started' logic)
        print(f"DEBUG: Heartbeat calling update_progress for enrollment {enrollment.id} (current: {enrollment.progress_percentage}%)")
        enrollment.update_progress()
        print(f"DEBUG: Heartbeat after update_progress for enrollment {enrollment.id} (now: {enrollment.progress_percentage}%)")

        # Broadcast the latest state
        self.broadcast_progress(enrollment.id)
        return api_success(message='Heartbeat processed')

    @staticmethod
    def broadcast_progress(enrollment_id):
        """Helper to broadcast progress to the enrollment group"""
        try:
            from asgiref.sync import async_to_sync
            from channels.layers import get_channel_layer
            enrollment = CourseEnrollment.objects.get(id=enrollment_id)
            channel_layer = get_channel_layer()
            print(f"DEBUG: Broadcasting to {enrollment_id} using layer: {channel_layer}")
            payload = {
                'type': 'enrollment_progress_update',
                'progress': float(enrollment.progress_percentage),
                'status': enrollment.status,
                'score': 0,
            }
            print(f"DEBUG: Broadcasting payload: {payload}")
            async_to_sync(channel_layer.group_send)(
                f"enrollment_{enrollment_id}",
                payload
            )
        except Exception as e:
            print(f"Error broadcasting progress: {e}")
    
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
        
        # Create module progress records in bulk
        module_progress_records = [
            StudentModuleProgress(enrollment=enrollment, module=module)
            for module in course.modules.all()
        ]
        StudentModuleProgress.objects.bulk_create(module_progress_records)
        
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
        
        # Broadcast update via WebSocket
        CourseEnrollmentViewSet.broadcast_progress(enrollment.id)
        
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
        
        return api_success(message='Content completed')


from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

@method_decorator(csrf_exempt, name='dispatch')
class ScormPostbackView(APIView):
    """
    Webhook handler for SCORM Cloud postbacks.
    SCORM Cloud sends a POST request with XML or JSON data when a registration is updated.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        print(">>> USING NEW SCORM FLOW")
        # SCORM Cloud can send data in different formats. 
        # Usually it's a 'registrationId' and 'completionStatus'
        reg_id = request.data.get('registrationId') or request.query_params.get('registrationId')
        
        if not reg_id:
            # Try parsing from raw body if it's XML or complex JSON
            try:
                import json
                data = json.loads(request.body)
                reg_id = data.get('registrationId')
            except:
                pass

        if not reg_id:
            return Response({"error": "No registrationId found"}, status=400)

        enrollment = CourseEnrollment.objects.filter(scorm_registration_id=reg_id).first()
        if not enrollment:
            return Response({"error": "Enrollment not found"}, status=404)

        # Trigger a sync with SCORM Cloud to get the most accurate details
        try:
            progress = get_scorm_registration_progress(reg_id)
            completion_amount = progress.get('completion_amount')
            if completion_amount is not None:
                if completion_amount <= 1:
                    completion_amount = completion_amount * 100
                completion_amount = max(0, min(100, float(completion_amount)))
                enrollment.progress_percentage = completion_amount
                if completion_amount >= 100:
                    enrollment.status = 'completed'
                    enrollment.completed_at = timezone.now()
                enrollment.save(update_fields=['progress_percentage', 'status', 'completed_at'])
                
                # Broadcast the new progress to the student's dashboard
                CourseEnrollmentViewSet.broadcast_progress(enrollment.id)
                
                return Response({"status": "success", "progress": completion_amount})
        except Exception as e:
            return Response({"error": str(e)}, status=500)

        return Response({"status": "received"})


class StudentCoursesAPIView(APIView):
    """Student-facing list of published courses"""
    permission_classes = [permissions.IsAuthenticated, IsEnrolledStudent]

    def get(self, request):
        courses = Course.objects.filter(status='published').select_related('category', 'instructor', 'instructor__tutor_profile')
        serializer = CourseListSerializer(courses, many=True)
        return api_success(data=serializer.data)


class StudentCourseDetailAPIView(APIView):
    """Student-facing course detail with modules and contents"""
    permission_classes = [permissions.IsAuthenticated, IsEnrolledStudent]

    def get(self, request, course_id):
        course = get_object_or_404(
            Course.objects.select_related('category', 'instructor')
            .prefetch_related('modules__contents', 'assessments')
            .annotate(
                total_modules_count=Count('modules', distinct=True),
                total_contents_count=Count('modules__contents', distinct=True),
                total_quizzes_count=Count(
                    'assessments',
                    filter=Q(assessments__assessment_type='quiz'),
                    distinct=True
                )
            ),
            id=course_id
        )

        if course.status != 'published' and not CourseEnrollment.objects.filter(course=course, student=request.user).exists():
            return api_error(message='Course not available', status_code=status.HTTP_403_FORBIDDEN)

        # Safety Check: If course is paid, we used to block here, 
        # but now we allow it so students can see the landing page and pay.
        # Access to actual lesson content is protected by enrollment/payment checks in other places.
        # if not course.is_free and course.price > 0:
        #     from .models import CoursePayment
        #     if not CoursePayment.objects.filter(course=course, student=request.user, status='confirmed').exists():
        #         return api_error(message='Payment verification required for this course.', status_code=status.HTTP_402_PAYMENT_REQUIRED)

        serializer = CourseSerializer(course, context={'request': request})
        data = serializer.data
        
        # Include student's attempts for this course to show "Done" status in frontend
        attempts = StudentAssessment.objects.filter(student=request.user, assessment__course=course)
        data['student_attempts'] = StudentAssessmentSerializer(attempts, many=True).data

        if course.is_scorm and CourseEnrollment.objects.filter(course=course, student=request.user).exists():
            enrollment = CourseEnrollment.objects.get(course=course, student=request.user)
            try:
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
        enrollments = (
            CourseEnrollment.objects
            .filter(student=request.user)
            .select_related('course', 'course__category', 'course__instructor', 'course__instructor__tutor_profile')
        )
        serializer = EnrollmentWithCourseSerializer(enrollments, many=True)
        return api_success(data=serializer.data)


class StudentCourseEnrollAPIView(APIView):
    """Enroll the current student in a published course"""
    permission_classes = [permissions.IsAuthenticated, IsEnrolledStudent]

    def post(self, request, course_id):
        course = get_object_or_404(Course, id=course_id, status='published')

        # Security Check: Only allow self-enrollment for free courses
        if not course.is_free and course.price > 0:
            return api_error(
                message='This is a paid course. Please complete payment to enroll.', 
                status_code=status.HTTP_402_PAYMENT_REQUIRED
            )

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
            modules = sorted(course.modules.all(), key=lambda m: m.order_number)
            if modules:
                first_module = modules[0]
                contents = sorted(first_module.contents.all(), key=lambda c: c.order_number)
                first_content = contents[0] if contents else None
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

        return api_success(data=data)


class StudentAssessmentViewSet(viewsets.ModelViewSet):
    """ViewSet for student assessments"""
    serializer_class = StudentAssessmentSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        queryset = StudentAssessment.objects.all().select_related(
            'student', 'student__student_profile', 
            'assessment', 'assessment__course'
        )
        
        assessment_id = self.request.query_params.get('assessment')
        course_id = self.request.query_params.get('course')
        
        if user.role == 'student':
            queryset = queryset.filter(student=user)
        elif user.role == 'tutor':
            # Tutor can only see assessments for courses they teach
            queryset = queryset.filter(assessment__course__instructor=user)
        elif user.role == 'admin':
            pass
        else:
            return StudentAssessment.objects.none()
            
        if assessment_id:
            queryset = queryset.filter(assessment_id=assessment_id)
        if course_id:
            queryset = queryset.filter(assessment__course_id=course_id)
            
        return queryset
    
    def create(self, request, *args, **kwargs):
        assessment_id = request.data.get('assessment')
        assessment = get_object_or_404(Assessment, id=assessment_id)
        
        # Check if student is enrolled in the course
        if not CourseEnrollment.objects.filter(student=request.user, course=assessment.course).exists():
            return Response({'error': 'Not enrolled in this course'}, status=status.HTTP_403_FORBIDDEN)
            
        # Safety Check: If course is paid, ensure confirmed payment exists
        if not assessment.course.is_free and assessment.course.price > 0:
            from .models import CoursePayment
            if not CoursePayment.objects.filter(course=assessment.course, student=request.user, status='confirmed').exists():
                return Response({'error': 'Payment verification required for this course.'}, status=status.HTTP_402_PAYMENT_REQUIRED)
            
        # Check start date
        if assessment.start_datetime and timezone.now() < assessment.start_datetime:
            return Response({'error': 'Assessment has not started yet'}, status=status.HTTP_400_BAD_REQUEST)
            
        # Check if student already has an attempt
        existing_attempt = StudentAssessment.objects.filter(student=request.user, assessment=assessment).first()
        if existing_attempt:
            if existing_attempt.status in ['submitted', 'graded']:
                # Return 200 with existing data if already submitted, frontend handles "Already submitted" message
                serializer = self.get_serializer(existing_attempt)
                return Response(serializer.data, status=status.HTTP_200_OK)
            # If not submitted, return the existing attempt so they can resume
            serializer = self.get_serializer(existing_attempt)
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        status_in_request = request.data.get('status', 'started')
        
        # Create new attempt
        attempt = StudentAssessment.objects.create(
            student=request.user,
            assessment=assessment,
            status=status_in_request
        )
        
        serializer = self.get_serializer(attempt)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    def _auto_grade_quiz(self, assessment, answers):
        """Auto-grade quiz based on correct answers in questions"""
        questions = assessment.questions if isinstance(assessment.questions, list) else []
        total_points = 0
        earned_points = 0
        
        for i, question in enumerate(questions):
            points = question.get('points', 10)
            total_points += points
            
            correct_answer = question.get('correct')
            student_answer = answers.get(str(i))
            
            try:
                if str(student_answer) == str(correct_answer):
                    earned_points += points
            except:
                pass
        
        if total_points > 0:
            score = (earned_points / total_points) * 100
        else:
            score = 0
        
        passed = score >= float(assessment.passing_score)
        return round(score, 2), passed
    
    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        """Submit an assessment attempt"""
        attempt = self.get_object()
        
        if attempt.status in ['submitted', 'graded']:
            return Response({'error': 'Already submitted'}, status=status.HTTP_400_BAD_REQUEST)
        
        assessment = attempt.assessment
        
        # Save answers for all assessment types
        answers = request.data.get('answers', attempt.answers or {})
        attempt.answers = answers
        
        # Check if it was auto-submitted (from request data or time check)
        is_auto = request.data.get('auto_submitted', False)
        reason = request.data.get('reason', 'manual')
        
        # Backend time check as a safety measure
        if assessment.end_datetime and timezone.now() > assessment.end_datetime:
            is_auto = True
            reason = 'time_expired'

        # Auto-grade for quizzes
        if assessment.assessment_type == 'quiz':
            score, passed = self._auto_grade_quiz(assessment, answers)
            attempt.score = score
            attempt.passed = passed
        
        # Update attempt status and timing
        attempt.status = 'submitted'
        attempt.submitted_at = timezone.now()
        
        # Calculate time taken
        if attempt.started_at:
            duration = timezone.now() - attempt.started_at
            attempt.time_taken_minutes = duration.seconds // 60
            
        attempt.save()
        
        response_data = StudentAssessmentSerializer(attempt).data
        if is_auto:
            response_data['auto_submitted_reason'] = reason
            
        return Response(response_data)
    
    @action(detail=True, methods=['post'])
    def grade(self, request, pk=None):
        """Tutor grades an exam or assignment"""
        if request.user.role not in ['admin', 'tutor']:
            return Response({'error': 'Only tutors can grade'}, status=status.HTTP_403_FORBIDDEN)
        
        attempt = self.get_object()
        score = request.data.get('score')
        feedback = request.data.get('feedback', '')
        passed = request.data.get('passed', False)
        answers = request.data.get('answers')
        
        if score is not None:
            attempt.score = score
        if feedback:
            attempt.feedback = feedback
        if passed is not None:
            attempt.passed = passed
        if answers:
            attempt.answers = answers
            
        attempt.status = 'graded'
        attempt.graded_by = request.user
        attempt.graded_at = timezone.now()
        attempt.save()
        
        return Response(StudentAssessmentSerializer(attempt).data)
    
    @action(detail=True, methods=['post'])
    def tab_switch(self, request, pk=None):
        """Record a tab switch event"""
        attempt = self.get_object()
        assessment = attempt.assessment
        
        attempt.tab_switch_count += 1
        attempt.last_tab_switch_at = timezone.now()
        attempt.save()
        
        # Auto-submit if too many tab switches
        if assessment.track_tab_switching and attempt.tab_switch_count >= assessment.max_tab_switches:
            attempt.status = 'auto_submitted'
            attempt.submitted_at = timezone.now()
            attempt.save()
            return Response({
                'message': 'Assessment auto-submitted due to tab switching',
                'auto_submitted': True,
                'tab_switches': attempt.tab_switch_count
            })
        
        return Response({
            'tab_switches': attempt.tab_switch_count,
            'max_allowed': assessment.max_tab_switches,
            'warning': f'Tab switch {attempt.tab_switch_count} of {assessment.max_tab_switches}'
        })
    

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
    
    def get_permissions(self):
        # Anyone authenticated can view announcements
        if self.action in ['list', 'retrieve']:
            return [permissions.IsAuthenticated()]
        # Only admins, staff, and course instructors can create/update/delete
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), CanManageCourses()]
        return [permissions.IsAuthenticated()]
    
    def get_queryset(self):
        course_id = self.kwargs.get('course_pk')
        if not course_id:
            return CourseAnnouncement.objects.none()
        
        user = self.request.user
        
        # Admin/Staff can see all announcements
        if user.role in ['admin', 'staff']:
            return CourseAnnouncement.objects.filter(course_id=course_id)
        
        # Tutor can see announcements for their courses
        if user.role == 'tutor':
            return CourseAnnouncement.objects.filter(
                course_id=course_id,
                course__instructor=user
            )
        
        # Student can see announcements for enrolled courses
        if user.role == 'student':
            return CourseAnnouncement.objects.filter(
                course_id=course_id,
                course__enrollments__student=user,
                course__status='published'
            )
        
        # Company - no access to announcements
        return CourseAnnouncement.objects.none()
    
    def perform_create(self, serializer):
        course_id = self.kwargs.get('course_pk')
        if not course_id:
            raise serializers.ValidationError({'course': 'Course is required'})
        
        course = get_object_or_404(Course, id=course_id)
        user = self.request.user
        
        # Check permissions for creation
        if user.role == 'tutor' and course.instructor != user:
            raise PermissionDenied('Only the course instructor can create announcements')
        
        if user.role == 'staff':
            staff_profile = getattr(user, 'staff_profile', None)
            if not staff_profile or not getattr(staff_profile, 'permissions', None) or not staff_profile.permissions.can_manage_courses:
                raise PermissionDenied('You do not have permission to create announcements')
        
        if user.role not in ['admin', 'staff', 'tutor']:
            raise PermissionDenied('You do not have permission to create announcements')
        
        serializer.save(
            course=course,
            created_by=user
        )
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
    
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return api_success(data=serializer.data)


class CoursePaymentViewSet(viewsets.ModelViewSet):
    """ViewSet for course payments and verification"""
    serializer_class = CoursePaymentSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        base_qs = CoursePayment.objects.select_related('student', 'student__student_profile', 'course', 'confirmed_by')
        # Admin and staff with payment permission can see all
        if user.role in ['admin', 'super_admin']:
            return base_qs.all()
            
        if user.role == 'staff':
            # Check staff permissions
            can_manage = False
            if hasattr(user, 'staff_profile') and hasattr(user.staff_profile, 'permissions'):
                can_manage = user.staff_profile.permissions.can_manage_payments
            
            if can_manage:
                return base_qs.all()
        
        # Student sees their own payments
        return base_qs.filter(student=user)
    
    def perform_create(self, serializer):
        # Student submits payment
        course_id = self.request.data.get('course')
        course = get_object_or_404(Course, id=course_id)
        
        # Check if already has a confirmed or pending payment
        if CoursePayment.objects.filter(student=self.request.user, course=course, status='confirmed').exists():
            raise serializers.ValidationError({"course": "You have already paid for this course"})
            
        if CoursePayment.objects.filter(student=self.request.user, course=course, status='pending').exists():
            raise serializers.ValidationError({"course": "You have a pending payment for this course"})
            
        serializer.save(
            student=self.request.user,
            amount=course.price,
            status='pending'
        )
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, CanManagePayments])
    def confirm(self, request, pk=None):
        """Confirm payment and enroll student"""
        payment = self.get_object()
        
        if payment.status != 'pending':
            return api_error(message=f'Payment is already {payment.status}')
            
        # Update payment status
        payment.status = 'confirmed'
        payment.confirmed_by = request.user
        payment.confirmed_at = timezone.now()
        payment.save()
        
        # Create enrollment
        enrollment, created = CourseEnrollment.objects.get_or_create(
            student=payment.student,
            course=payment.course,
            defaults={
                'status': 'active',
                'total_modules_at_enrollment': payment.course.total_modules or payment.course.modules.count()
            }
        )
        
        if not created and enrollment.total_modules_at_enrollment == 0:
            enrollment.total_modules_at_enrollment = payment.course.total_modules
            enrollment.save(update_fields=['total_modules_at_enrollment'])
        
        if created:
            payment.course.enrolled_count = CourseEnrollment.objects.filter(course=payment.course, status='active').count()
            payment.course.save()
            
            # Create module progress records
            from .models import StudentModuleProgress
            for module in payment.course.modules.all():
                StudentModuleProgress.objects.create(
                    enrollment=enrollment,
                    module=module
                )
        
        return api_success(
            data=CoursePaymentSerializer(payment).data,
            message=f'Payment confirmed and student enrolled in {payment.course.title}'
        )
        
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, CanManagePayments])
    def reject(self, request, pk=None):
        """Reject payment"""
        payment = self.get_object()
        reason = request.data.get('reason', 'Payment verification failed')
        
        if payment.status != 'pending':
            return api_error(message=f'Payment is already {payment.status}')
            
        payment.status = 'rejected'
        payment.confirmed_by = request.user
        payment.confirmed_at = timezone.now()
        payment.rejection_reason = reason
        payment.save()
        
        return api_success(
            data=CoursePaymentSerializer(payment).data,
            message='Payment rejected'
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return api_success(data=serializer.data)


class LiveSessionViewSet(viewsets.ModelViewSet):
    """ViewSet for live sessions - full CRUD for admin/tutor, read for enrolled students"""
    serializer_class = LiveSessionSerializer

    def get_permissions(self):
        if self.action in ['list', 'retrieve', 'join_link']:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated(), CanManageCourses()]

    def get_queryset(self):
        course_id = self.kwargs.get('course_pk')
        return LiveSession.objects.filter(course_id=course_id).prefetch_related('attendances', 'tutor_note')

    def perform_create(self, serializer):
        course_id = self.kwargs.get('course_pk')
        course = get_object_or_404(Course, id=course_id)
        user = self.request.user
        if user.role == 'tutor' and course.instructor != user:
            raise PermissionDenied('You can only create sessions for your own courses')
        serializer.save(course=course)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True, context={'request': request})
        return api_success(data=serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, context={'request': request})
        return api_success(data=serializer.data)

    @action(detail=True, methods=['get'], url_path='join-link')
    def join_link(self, request, pk=None, course_pk=None):
        """Return the meet link only if the session is currently active"""
        session = self.get_object()
        session_status = session.get_status()
        if session_status != 'active':
            return api_error(
                message=f'Session is not active. Current status: {session_status}',
                status_code=403
            )
        if not session.meet_link:
            return api_error(message='No meeting link available for this session', status_code=404)
        return api_success(data={'meet_link': session.meet_link, 'status': session_status})

    @action(detail=True, methods=['post'], url_path='attendance')
    def mark_attendance(self, request, pk=None, course_pk=None):
        """Mark attendance for students — tutor/admin only. Accepts list of {student_id, status, notes}"""
        session = self.get_object()
        user = request.user
        if user.role not in ['admin', 'tutor', 'super_admin']:
            return api_error(message='Only tutors and admins can mark attendance', status_code=403)
        records = request.data.get('records', [])
        if not isinstance(records, list):
            return api_error(message='Provide records as a list of {student_id, status, notes}', status_code=400)
        results = []
        for record in records:
            student_id = record.get('student_id')
            att_status = record.get('status', 'absent')
            notes = record.get('notes', '')
            if not student_id:
                continue
            attendance, _ = Attendance.objects.update_or_create(
                session=session,
                student_id=student_id,
                defaults={'status': att_status, 'notes': notes, 'marked_by': user}
            )
            results.append(AttendanceSerializer(attendance).data)
        return api_success(data=results, message=f'Attendance marked for {len(results)} students')

    @action(detail=True, methods=['post'], url_path='summary')
    def add_summary(self, request, pk=None, course_pk=None):
        """Post-class summary, homework, recording link — marks session completed"""
        session = self.get_object()
        user = request.user
        if user.role not in ['admin', 'tutor', 'super_admin']:
            return api_error(message='Only tutors and admins can add session summaries', status_code=403)
        session.summary = request.data.get('summary', session.summary)
        session.topics_covered = request.data.get('topics_covered', session.topics_covered)
        session.homework = request.data.get('homework', session.homework)
        session.recording_link = request.data.get('recording_link', session.recording_link)
        session.is_completed = True
        session.save()
        # Optionally save tutor notes
        teaching_notes = request.data.get('teaching_notes')
        performance_observations = request.data.get('performance_observations')
        next_session_prep = request.data.get('next_session_prep')
        if any([teaching_notes, performance_observations, next_session_prep]):
            TutorNote.objects.update_or_create(
                session=session,
                defaults={
                    'teaching_notes': teaching_notes,
                    'performance_observations': performance_observations,
                    'next_session_prep': next_session_prep,
                }
            )
        serializer = self.get_serializer(session, context={'request': request})
        return api_success(data=serializer.data, message='Session summary saved and session marked as completed')

    @action(detail=True, methods=['get'], url_path='attendance-report')
    def attendance_report(self, request, pk=None, course_pk=None):
        """Full attendance list for a session — tutor/admin only"""
        session = self.get_object()
        user = request.user
        if user.role not in ['admin', 'tutor', 'super_admin']:
            return api_error(message='Only tutors and admins can view attendance reports', status_code=403)
        # Get all enrolled students and merge with attendance
        enrollments = CourseEnrollment.objects.filter(course=session.course, status='active').select_related('student')
        attendance_map = {a.student_id: a for a in session.attendances.all()}
        report = []
        for enr in enrollments:
            att = attendance_map.get(enr.student_id)
            report.append({
                'student_id': enr.student_id,
                'student_email': enr.student.email,
                'student_name': (
                    getattr(getattr(enr.student, 'student_profile', None), 'full_name', None)
                    or enr.student.email.split('@')[0]
                ),
                'status': att.status if att else 'not_marked',
                'notes': att.notes if att else None,
                'marked_at': att.marked_at.isoformat() if att else None,
            })
        return api_success(data={
            'session': LiveSessionSerializer(session, context={'request': request}).data,
            'report': report,
            'total_enrolled': len(report),
            'present': sum(1 for r in report if r['status'] == 'present'),
            'absent': sum(1 for r in report if r['status'] == 'absent'),
            'late': sum(1 for r in report if r['status'] == 'late'),
            'excused': sum(1 for r in report if r['status'] == 'excused'),
        })


class AttendanceOverviewView(APIView):
    """Course-wide day-wise attendance overview"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, course_pk):
        course = get_object_or_404(Course, id=course_pk)
        user = request.user
        if user.role not in ['admin', 'tutor', 'super_admin']:
            return api_error(message='Only tutors and admins can view attendance overview', status_code=403)
        sessions = LiveSession.objects.filter(course=course).prefetch_related('attendances')
        total_enrolled = CourseEnrollment.objects.filter(course=course, status='active').count()
        overview = []
        for session in sessions:
            att_count = session.attendances.count()
            present_count = session.attendances.filter(status__in=['present', 'late']).count()
            pct = round((present_count / total_enrolled * 100), 1) if total_enrolled > 0 else 0
            overview.append({
                'session_id': session.id,
                'day_number': session.day_number,
                'title': session.title,
                'date': str(session.date),
                'status': session.get_status(),
                'total_enrolled': total_enrolled,
                'present': present_count,
                'absent': att_count - present_count,
                'not_marked': total_enrolled - att_count,
                'attendance_pct': pct,
            })
        # Low attendance students (<75%)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        enrolled_users = User.objects.filter(enrollments__course=course, enrollments__status='active')
        session_count = sessions.count()
        low_attendance = []
        for student in enrolled_users:
            present = Attendance.objects.filter(
                session__course=course, student=student, status__in=['present', 'late']
            ).count()
            pct = round((present / session_count * 100), 1) if session_count > 0 else 0
            if pct < 75:
                low_attendance.append({
                    'student_id': student.id,
                    'student_email': student.email,
                    'student_name': (
                        getattr(getattr(student, 'student_profile', None), 'full_name', None)
                        or student.email.split('@')[0]
                    ),
                    'sessions_attended': present,
                    'total_sessions': session_count,
                    'attendance_pct': pct,
                })
        return api_success(data={
            'course_id': course.id,
            'course_title': course.title,
            'total_sessions': session_count,
            'total_enrolled': total_enrolled,
            'day_wise': overview,
            'low_attendance_students': sorted(low_attendance, key=lambda x: x['attendance_pct']),
        })


class CeleryHealthCheckView(APIView):
    """Test if Celery is working properly."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        """Check Celery health."""
        try:
            from celery import current_app
            from .tasks import debug_task
            
            # Try to queue a simple task
            task = debug_task.delay()
            
            return api_success(data={
                'celery_status': 'healthy',
                'task_id': task.id,
                'message': 'Celery is working. You can check task status by polling the task_id.'
            })
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Celery health check failed: {str(e)}", exc_info=True)
            return api_error(message=f'Celery is not working: {str(e)}', status_code=500)
