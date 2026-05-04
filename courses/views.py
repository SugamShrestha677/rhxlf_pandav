from rest_framework import viewsets, status, permissions
from rest_framework import serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db import models as db_models
from cloudinary.uploader import upload

from .models import (
    Category, Course, CourseModule, ModuleContent, CourseEnrollment,
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
    CourseAnnouncementSerializer
)
from .permissions import CanManageCourses, IsCourseInstructor, IsEnrolledStudent, IsStudentOwner
from LMS.api import api_error, api_success


class CategoryViewSet(viewsets.ModelViewSet):
    """ViewSet for course categories"""
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    
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
        return CourseSerializer
    
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
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
    
    def get_queryset(self):
        user = self.request.user
        
        # If authenticated and admin/staff, show all
        if user.is_authenticated and user.role in ['admin', 'staff']:
            return Course.objects.all()
        
        # If tutor, show their courses
        if user.is_authenticated and user.role == 'tutor':
            return Course.objects.filter(instructor=user)
        
        # If student, show published courses
        return Course.objects.filter(status='published')
    
    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """Publish a course"""
        course = self.get_object()
        
        if not request.user.role in ['admin', 'staff'] and course.instructor != request.user:
            return api_error(message='Only admin or course instructor can publish', status_code=status.HTTP_403_FORBIDDEN)
        
        course.publish()
        return api_success(message='Course published successfully')
    
    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        """Archive a course"""
        course = self.get_object()
        if not request.user.role in ['admin', 'staff'] and course.instructor != request.user:
            return api_error(message='Only admin or course instructor can archive', status_code=status.HTTP_403_FORBIDDEN)
        course.archive()
        return api_success(message='Course archived')
    
    
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
        
        return api_success(message='Content completed')


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