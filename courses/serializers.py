from rest_framework import serializers
from django.utils.text import slugify
from django.utils.crypto import get_random_string
from .models import (
    Course, CourseModule, ModuleContent, CourseEnrollment,
    StudentModuleProgress, StudentContentProgress,
    Assessment, StudentAssessment, Certificate,
    CourseReview, CourseAnnouncement
)
from django.conf import settings


class ModuleContentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModuleContent
        fields = [
            'id', 'title', 'content_type', 'description',
            'file_url', 'video_url', 'external_link', 'body_text',
            'order_number', 'duration_minutes', 'is_required',
            'minimum_score', 'view_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'view_count', 'created_at', 'updated_at']


class CourseModuleSerializer(serializers.ModelSerializer):
    contents = ModuleContentSerializer(many=True, read_only=True)
    content_count = serializers.SerializerMethodField()
    
    class Meta:
        model = CourseModule
        fields = [
            'id', 'title', 'description', 'order_number',
            'duration_minutes', 'is_published', 'contents',
            'content_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_content_count(self, obj):
        return obj.contents.count()


class CourseModuleBasicSerializer(serializers.ModelSerializer):
    """Serializer without nested contents (for performance)"""
    content_count = serializers.SerializerMethodField()
    
    class Meta:
        model = CourseModule
        fields = [
            'id', 'title', 'description', 'order_number',
            'duration_minutes', 'is_published', 'content_count'
        ]
    
    def get_content_count(self, obj):
        return obj.contents.count()


class AssessmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Assessment
        fields = [
            'id', 'title', 'description', 'assessment_type',
            'max_score', 'passing_score', 'duration_minutes',
            'questions', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class CourseSerializer(serializers.ModelSerializer):
    """Full course serializer"""
    modules = CourseModuleSerializer(many=True, read_only=True)
    assessments = AssessmentSerializer(many=True, read_only=True)
    instructor_name = serializers.CharField(source='instructor.tutor_profile.full_name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.email', read_only=True)
    
    class Meta:
        model = Course
        fields = [
            'id', 'title', 'slug', 'description', 'short_description',
            'level', 'duration_weeks', 'total_hours',
            'thumbnail_url', 'preview_video_url',
            'price', 'is_free',
            'status', 'start_date', 'end_date', 'enrollment_deadline',
            'max_students', 'enrolled_count',
            'instructor', 'instructor_name', 'created_by', 'created_by_name',
            'prerequisites', 'target_audience', 'learning_outcomes',
            'modules', 'assessments',
            'total_modules', 'total_contents', 'total_quizzes',
            'created_at', 'updated_at', 'published_at'
        ]
        read_only_fields = [
            'id', 'slug', 'enrolled_count', 'instructor_name',
            'created_by_name', 'total_modules', 'total_contents',
            'total_quizzes', 'created_at', 'updated_at', 'published_at'
        ]


class CourseCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating courses"""
    
    class Meta:
        model = Course
        fields = [
            'title', 'description', 'short_description',
            'level', 'duration_weeks', 'total_hours',
            'thumbnail_url', 'preview_video_url',
            'price', 'is_free',
            'start_date', 'end_date', 'enrollment_deadline',
            'max_students', 'instructor',
            'prerequisites', 'target_audience', 'learning_outcomes'
        ]
    
    def validate(self, data):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            raise serializers.ValidationError("Authentication required")
        
        # Check user permissions
        user = request.user
        if user.role not in ['admin', 'staff', 'tutor']:
            raise serializers.ValidationError("You don't have permission to create courses")
        
        # Staff needs permission
        if user.role == 'staff':
            staff_profile = user.staff_profile
            if not staff_profile.permissions.can_manage_courses:
                raise serializers.ValidationError("staff, You don't have permission to create courses")
        
        # Validate instructor
        instructor = data.get('instructor')
        if instructor and instructor.role not in ['tutor', 'admin', 'staff']:
            raise serializers.ValidationError({"instructor": "Instructor must be a tutor, admin, or staff"})
        
        return data
    
    def create(self, validated_data):
        # Generate unique slug
        slug = slugify(validated_data['title'])
        while Course.objects.filter(slug=slug).exists():
            slug = f"{slugify(validated_data['title'])}-{get_random_string(4)}"
        
        course = Course.objects.create(
            **validated_data,
            slug=slug,
            created_by=self.context['request'].user
        )
        
        # If no instructor set, use the course name as a placeholder
        if not course.instructor:
            course.instructor = self.context['request'].user
        
        course.save()
        
        return course


class CourseEnrollmentSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.student_profile.full_name', read_only=True)
    student_email = serializers.EmailField(source='student.email', read_only=True)
    course_title = serializers.CharField(source='course.title', read_only=True)
    
    class Meta:
        model = CourseEnrollment
        fields = [
            'id', 'student', 'student_name', 'student_email',
            'course', 'course_title', 'status',
            'progress_percentage', 'completed_modules',
            'total_modules_at_enrollment',
            'enrolled_at', 'completed_at', 'last_accessed_at',
            'certificate_issued', 'certificate_url'
        ]
        read_only_fields = [
            'id', 'progress_percentage', 'completed_modules',
            'enrolled_at', 'completed_at', 'last_accessed_at',
            'certificate_issued', 'certificate_url'
        ]


class StudentAssessmentSerializer(serializers.ModelSerializer):
    student_email = serializers.EmailField(source='student.email', read_only=True)
    assessment_title = serializers.CharField(source='assessment.title', read_only=True)
    
    class Meta:
        model = StudentAssessment
        fields = [
            'id', 'student', 'student_email', 'assessment', 'assessment_title',
            'score', 'passed', 'answers', 'attempt_number',
            'time_taken_minutes', 'submitted_at'
        ]
        read_only_fields = ['id', 'submitted_at']


class CertificateSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.student_profile.full_name', read_only=True)
    course_title = serializers.CharField(source='course.title', read_only=True)
    
    class Meta:
        model = Certificate
        fields = [
            'id', 'student', 'student_name', 'course', 'course_title',
            'unique_code', 'certificate_url', 'final_score', 'issued_at'
        ]
        read_only_fields = ['id', 'unique_code', 'certificate_url', 'issued_at']


class CourseReviewSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.student_profile.full_name', read_only=True)
    
    class Meta:
        model = CourseReview
        fields = [
            'id', 'student', 'student_name', 'course',
            'rating', 'review_text', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'student', 'created_at', 'updated_at']
    
    def validate(self, data):
        request = self.context.get('request')
        if CourseReview.objects.filter(student=request.user, course=data['course']).exists():
            raise serializers.ValidationError("You have already reviewed this course")
        return data


class CourseAnnouncementSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.email', read_only=True)
    
    class Meta:
        model = CourseAnnouncement
        fields = [
            'id', 'course', 'title', 'content',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_by_name', 'created_at', 'updated_at']