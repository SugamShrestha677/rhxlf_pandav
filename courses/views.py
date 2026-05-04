from rest_framework import viewsets, status, permissions
from rest_framework import serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db import models as db_models
from django.db.models.functions import TruncDate
from datetime import timedelta

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
    CourseAnnouncementSerializer, CourseListSerializer,
    EnrollmentWithCourseSerializer
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
        return api_success(data=serializer.data)


class StudentEnrolledCoursesAPIView(APIView):
    """Student-facing list of enrollments with course info"""
    permission_classes = [permissions.IsAuthenticated, IsEnrolledStudent]

    def get(self, request):
        enrollments = (
            CourseEnrollment.objects
            .filter(student=request.user)
            .select_related('course', 'course__category', 'course__instructor')
        )
        serializer = EnrollmentWithCourseSerializer(enrollments, many=True)
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