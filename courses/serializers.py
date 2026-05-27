import os
from django.utils import timezone

from rest_framework import serializers
from django.utils.text import slugify
from django.utils.crypto import get_random_string
from .models import (
    Category, Course, CourseModule, ModuleContent, CourseEnrollment, CourseResource,
    StudentModuleProgress, StudentContentProgress,
    Assessment, StudentAssessment, Certificate,
    CourseReview, CourseAnnouncement, CoursePayment,
    LiveSession, Attendance, TutorNote
)
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from cloudinary.uploader import upload
from cloudinary.utils import cloudinary_url


def get_cloudinary_url(value):
    if not value:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.lower() in ['none', 'null', 'undefined']:
            return None
        
        # Inject Cloudinary optimization parameters if it's a cloudinary URL
        if 'res.cloudinary.com' in cleaned and '/upload/' in cleaned:
            # Add q_auto (auto quality) and f_auto (auto format)
            # This significantly reduces image size while maintaining quality
            if '/q_auto,f_auto/' not in cleaned:
                cleaned = cleaned.replace('/upload/', '/upload/q_auto,f_auto/')
        
        return cleaned
    
    url = getattr(value, 'url', None)
    if isinstance(url, str) and url.strip():
        return get_cloudinary_url(url)
        
    public_id = getattr(value, 'public_id', None)
    if isinstance(public_id, str) and public_id.strip():
        generated_url, _ = cloudinary_url(public_id)
        return get_cloudinary_url(generated_url)
    return None


class ScormUploadSerializer(serializers.Serializer):
    scorm_zip = serializers.FileField()


class CategorySerializer(serializers.ModelSerializer):
    course_count = serializers.IntegerField(read_only=True)
    
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'description', 'icon_url', 'course_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'course_count', 'created_at', 'updated_at']


class ModuleContentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModuleContent
        fields = [
            'id', 'title', 'content_type', 'description',
            'file_url', 'video_url', 'audio_url', 'external_link', 'body_text',
            'scorm_course_id', 'scorm_import_job_id', 'scorm_status', 'scorm_version',
            'order_number', 'duration_minutes', 'is_required',
            'minimum_score', 'view_count', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'view_count', 'scorm_course_id', 'scorm_import_job_id', 
            'scorm_status', 'scorm_version', 'created_at', 'updated_at'
        ]


class CourseResourceSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    file_name = serializers.SerializerMethodField()
    module_title = serializers.CharField(source='module.title', read_only=True)
    module_order = serializers.IntegerField(source='module.order_number', read_only=True)
    
    # Make course read-only - will be set from URL
    course = serializers.PrimaryKeyRelatedField(read_only=True)
    # File field is optional and read-only in response
    file = serializers.URLField(read_only=True)
    
    class Meta:
        model = CourseResource
        fields = [
            'id', 'course', 'module', 'module_id', 'live_session', 'live_session_id', 'module_title', 'module_order',
            'title', 'description', 'file', 'file_url', 'file_name', 'file_size',
            'external_link', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'course', 'file', 'file_url', 'file_name', 'file_size', 'created_at', 'updated_at']
    
    def get_file_url(self, obj):
        return get_cloudinary_url(obj.file) if obj.file else None
    
    def get_file_name(self, obj):
        return obj.file_name or None
    
    def validate(self, data):
        """Validate that either file or external link is provided"""
        request = self.context.get('request')
        has_file = request and request.FILES.get('file')
        has_external_link = data.get('external_link')
        
        if not has_file and not has_external_link and not self.instance:
            raise serializers.ValidationError({
                'error': 'Provide either a file or an external link.'
            })
        
        return data


class CourseResourceCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating resources - handles file upload"""
    file_upload = serializers.FileField(required=False, write_only=True)
    module_id = serializers.IntegerField(required=False, write_only=True, allow_null=True)
    live_session_id = serializers.IntegerField(required=False, write_only=True, allow_null=True)
    
    class Meta:
        model = CourseResource
        fields = [
            'title', 'description', 'external_link', 'file_upload', 'module_id', 'live_session_id'
        ]
    
    def validate(self, data):
        file_upload = data.get('file_upload')
        external_link = data.get('external_link')
        
        if not file_upload and not external_link:
            raise serializers.ValidationError({
                'error': 'Provide either a file or an external link.'
            })
        
        return data
    
    def create(self, validated_data):
        file_upload = validated_data.pop('file_upload', None)
        module_id = validated_data.pop('module_id', None)
        live_session_id = validated_data.pop('live_session_id', None)
        external_link = validated_data.pop('external_link', None)
        
        # Get course from context (set by view)
        course = self.context.get('course')
        if not course:
            raise serializers.ValidationError({'course': 'Course is required'})
        
        # Get module if specified
        module = None
        if module_id:
            try:
                module = CourseModule.objects.get(id=module_id, course=course)
            except CourseModule.DoesNotExist:
                raise serializers.ValidationError({'module_id': 'Invalid module'})
        
        # Get live session if specified
        live_session = None
        if live_session_id:
            try:
                from courses.models import LiveSession
                live_session = LiveSession.objects.get(id=live_session_id, course=course)
            except Exception:
                raise serializers.ValidationError({'live_session_id': 'Invalid live session'})
        
        # Upload file to Cloudinary if provided
        file_url = None
        file_name = None
        file_size = 0
        
        if file_upload:
            try:
                # Save to local server instead of Cloudinary as requested
                fs = FileSystemStorage()
                # Create a specific path for course resources
                folder_path = f'course_resources/{course.id}'
                filename = fs.save(os.path.join(folder_path, file_upload.name), file_upload)
                
                # Get the relative URL
                relative_url = fs.url(filename)
                
                # Construct absolute URL for the frontend
                api_base_url = getattr(settings, 'API_BASE_URL', 'http://localhost:8000').rstrip('/')
                file_url = f"{api_base_url}{relative_url}"
                
                file_name = file_upload.name
                file_size = file_upload.size
            except Exception as e:
                raise serializers.ValidationError({'file_upload': f'Local upload failed: {str(e)}'})
        
        # Create resource
        resource = CourseResource.objects.create(
            course=course,
            module=module,
            live_session=live_session,
            title=validated_data.get('title'),
            description=validated_data.get('description', ''),
            file=file_url,
            file_name=file_name,
            file_size=file_size,
            external_link=external_link,
        )
        
        return resource


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
        return len(obj.contents.all())


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
        return len(obj.contents.all())


class AssessmentSerializer(serializers.ModelSerializer):
    total_attempts = serializers.SerializerMethodField()
    graded_attempts = serializers.SerializerMethodField()
    pending_attempts = serializers.SerializerMethodField()
    student_attempt = serializers.SerializerMethodField()
    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.all(), required=False)
    
    class Meta:
        model = Assessment
        fields = [
            'id', 'course', 'module', 'live_session', 'title', 'description', 'assessment_type',
            'max_score', 'passing_score', 'duration_minutes',
            'start_datetime', 'end_datetime',
            'submission_type', 'allowed_file_types',
            'allow_late_submission', 'late_submission_deadline', 'max_file_size_mb',
            'questions', 'track_tab_switching', 'max_tab_switches',
            'total_attempts',
            'graded_attempts',
            'pending_attempts',
            'student_attempt',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_total_attempts(self, obj):
        return obj.student_attempts.count()

    def get_graded_attempts(self, obj):
        from django.db.models import Q
        return obj.student_attempts.filter(
            Q(status='graded') | Q(status='submitted', score__isnull=False)
        ).count()

    def get_pending_attempts(self, obj):
        return obj.student_attempts.filter(status='pending').count()

    def get_student_attempt(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated or request.user.role != 'student':
            return None

        attempts = getattr(obj, '_prefetched_student_attempts', None)
        if attempts is None:
            attempts = obj.student_attempts.filter(student=request.user).select_related(
                'student', 'student__student_profile', 'assessment', 'assessment__course'
            )

        attempt = next(iter(attempts), None)
        if not attempt:
            return None

        return StudentAssessmentSerializer(attempt, context=self.context).data
    
    def get_passing_score_percentage(self, obj):
        return (obj.passing_score / obj.max_score * 100) if obj.max_score > 0 else 0

    def get_is_active(self, obj):
        from django.utils import timezone
        now = timezone.now()
        if obj.start_datetime and now < obj.start_datetime:
            return False
        if obj.end_datetime and now > obj.end_datetime:
            return False
        return True
    
    def validate_questions(self, value):
        """Validate questions format based on assessment type"""
        if not isinstance(value, list):
            return value
        
        for q in value:
            if not isinstance(q, dict):
                continue
            
            question_type = q.get('type', 'mcq')
            
            if question_type == 'mcq':
                # MCQ must have options and correct answer
                if not q.get('options') or len(q.get('options', [])) < 2:
                    raise serializers.ValidationError("MCQ questions must have at least 2 options")
            elif question_type == 'long_answer':
                # Long answer needs question text only
                if not q.get('question'):
                    raise serializers.ValidationError("Long answer questions must have question text")
        
        return value
    
class AssessmentCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating assessments - course is auto-set from URL"""
    
    class Meta:
        model = Assessment
        fields = [
            'module', 'title', 'description', 'assessment_type',
            'max_score', 'passing_score', 'duration_minutes',
            'start_datetime', 'end_datetime',
            'submission_type', 'allowed_file_types',
            'allow_late_submission', 'late_submission_deadline', 'max_file_size_mb',
            'questions', 'track_tab_switching', 'max_tab_switches',
        ]
    
    def validate(self, data):
        assessment_type = data.get('assessment_type')
        
        # Exam requires questions
        if assessment_type in ['quiz', 'exam']:
            if not data.get('questions'):
                raise serializers.ValidationError({"questions": "Questions are required for quizzes and exams"})
        
        # Assignment requires submission type
        if assessment_type == 'assignment':
            if not data.get('submission_type'):
                data['submission_type'] = 'file'
        
        return data


class CourseSerializer(serializers.ModelSerializer):
    """Full course serializer"""
    modules = CourseModuleSerializer(many=True, read_only=True)
    assessments = AssessmentSerializer(many=True, read_only=True)
    instructor_name = serializers.CharField(source='instructor.tutor_profile.full_name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.email', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    thumbnail_url = serializers.SerializerMethodField()
    preview_video_url = serializers.SerializerMethodField()
    
    total_modules = serializers.SerializerMethodField()
    total_contents = serializers.SerializerMethodField()
    total_quizzes = serializers.SerializerMethodField()
    scorm_upload_status = serializers.SerializerMethodField()
    scorm_launch_url = serializers.SerializerMethodField()
    scorm_launch_error = serializers.SerializerMethodField()

    def _has_content_level_scorm(self, obj):
        """Return True when the course already uses the new content-level SCORM flow."""
        cached_value = getattr(obj, '_content_level_scorm_exists', None)
        if cached_value is not None:
            return cached_value

        prefetched_modules = getattr(obj, '_prefetched_objects_cache', {}).get('modules')
        if prefetched_modules is not None:
            for module in prefetched_modules:
                prefetched_contents = getattr(module, '_prefetched_objects_cache', {}).get('contents')
                if prefetched_contents is None:
                    continue
                for content in prefetched_contents:
                    if content.content_type == 'scorm' and content.scorm_course_id:
                        obj._content_level_scorm_exists = True
                        return True

        exists = obj.modules.filter(contents__content_type='scorm').exclude(
            contents__scorm_course_id__isnull=True
        ).exists()
        obj._content_level_scorm_exists = exists
        return exists
    
    def get_scorm_upload_status(self, obj):
        """Return whether SCORM upload is pending, completed, or failed."""
        if not obj.is_scorm:
            return None
        if obj.scorm_import_job_id:
            return 'completed'
        return 'pending'

    def _get_scorm_launch_data(self, obj, request):
        if hasattr(obj, '_scorm_launch_data'):
            return obj._scorm_launch_data

        # The new flow launches SCORM at the content level. If the course already
        # contains SCORM contents, avoid exposing stale course-level launch errors.
        if self._has_content_level_scorm(obj):
            obj._scorm_launch_data = (None, None)
            return obj._scorm_launch_data

        if not obj.is_scorm or not obj.scorm_course_id:
            obj._scorm_launch_data = (None, None)
            return obj._scorm_launch_data

        # Check status first
        if obj.scorm_import_job_id:
            from django.core.cache import cache
            cache_key = f"scorm_status_{obj.scorm_import_job_id}"
            status_data = cache.get(cache_key)
            if status_data and status_data.get('status', '').lower() not in ['finished', 'complete']:
                obj._scorm_launch_data = (None, "Course is still being processed by SCORM Cloud. Please wait...")
                return obj._scorm_launch_data

        from .services import get_scorm_launch_link
        try:
            _, launch_url = get_scorm_launch_link(obj, request.user)
            obj._scorm_launch_data = (launch_url, None)
        except Exception as e:
            error_str = str(e)
            if "Could not find course ID" in error_str:
                if obj.scorm_import_job_id:
                    error_str = "Course is still initializing on SCORM Cloud. Try again in 30 seconds."
                else:
                    error_str = "Course not found on SCORM Cloud. Please contact admin to re-upload."
            obj._scorm_launch_data = (None, error_str)

        return obj._scorm_launch_data

    def get_scorm_launch_url(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        view = self.context.get('view')
        if view and view.action != 'retrieve':
            return None
        return self._get_scorm_launch_data(obj, request)[0]

    def get_scorm_launch_error(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        view = self.context.get('view')
        if view and view.action != 'retrieve':
            return None
        return self._get_scorm_launch_data(obj, request)[1]
    
    def get_total_modules(self, obj):
        return getattr(obj, 'total_modules_count', len(obj.modules.all()))

    def get_total_contents(self, obj):
        return getattr(obj, 'total_contents_count', obj.total_contents)

    def get_total_quizzes(self, obj):
        return getattr(obj, 'total_quizzes_count', obj.assessments.filter(assessment_type='quiz').count())

    def get_thumbnail_url(self, obj):
        return get_cloudinary_url(obj.thumbnail)

    def get_preview_video_url(self, obj):
        return get_cloudinary_url(obj.preview_video)
    
    class Meta:
        model = Course
        fields = [
            'id', 'title', 'slug', 'description', 'short_description',
            'category', 'category_name',
            'level', 'duration_weeks', 'total_hours',
            'thumbnail_url', 'preview_video_url',
            'thumbnail', 'preview_video',
            'price', 'is_free',
            'status', 'start_date', 'end_date', 'enrollment_deadline',
            'max_students', 'enrolled_count',
            'instructor', 'instructor_name', 'created_by', 'created_by_name',
            'prerequisites', 'target_audience', 'learning_outcomes',
            'modules', 'assessments',
            'total_modules', 'total_contents', 'total_quizzes',
            'is_scorm', 'scorm_course_id', 'scorm_import_job_id', 'scorm_upload_status',
            'scorm_launch_url', 'scorm_launch_error',
            'course_type', 'created_at', 'updated_at', 'published_at'
        ]
        read_only_fields = [
            'id', 'slug', 'enrolled_count', 'instructor_name',
            'created_by_name', 'total_modules', 'total_contents',
            'total_quizzes', 'scorm_upload_status', 'created_at', 'updated_at', 'published_at'
        ]


class CourseListSerializer(serializers.ModelSerializer):
    """Lightweight course serializer for student listings"""
    category_name = serializers.CharField(source='category.name', read_only=True)
    instructor_name = serializers.CharField(source='instructor.tutor_profile.full_name', read_only=True)
    thumbnail_url = serializers.SerializerMethodField()
    preview_video_url = serializers.SerializerMethodField()

    def get_thumbnail_url(self, obj):
        return get_cloudinary_url(obj.thumbnail)

    def get_preview_video_url(self, obj):
        return get_cloudinary_url(obj.preview_video)

    class Meta:
        model = Course
        fields = [
            'id', 'title', 'slug', 'short_description',
            'category', 'category_name',
            'level', 'duration_weeks', 'total_hours',
            'thumbnail_url', 'preview_video_url', 'thumbnail', 'preview_video', 'price', 'is_free',
            'status', 'start_date', 'end_date', 'enrollment_deadline',
            'max_students', 'enrolled_count',
            'instructor', 'instructor_name',
            'is_scorm', 'course_type',
            'created_at', 'updated_at', 'published_at'
        ]
        read_only_fields = ['id', 'slug', 'enrolled_count', 'created_at', 'updated_at', 'published_at']


class CourseCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating courses"""
    
    thumbnail_file = serializers.ImageField(write_only=True, required=False, allow_null=True)
    preview_video_file = serializers.FileField(write_only=True, required=False, allow_null=True)
    
    class Meta:
        model = Course
        fields = [
            'title', 'description', 'short_description', 'category',
            'level', 'duration_weeks', 'total_hours',
            'thumbnail_file', 'preview_video_file',  
            'price', 'is_free', 'status',
            'start_date', 'end_date', 'enrollment_deadline',
            'max_students', 'instructor', 'course_type',
            'prerequisites', 'target_audience', 'learning_outcomes'
        ]
        read_only_fields = ['thumbnail', 'preview_video']
    
    def validate(self, data):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            raise serializers.ValidationError("Authentication required")
        
        # Check user permissions
        user = request.user
        if user.role not in ['admin', 'super_admin', 'staff', 'tutor']:
            raise serializers.ValidationError("You don't have permission to create courses")
        
        # Staff needs permission
        if user.role == 'staff':
            staff_profile = user.staff_profile
            if not staff_profile.permissions.can_manage_courses:
                raise serializers.ValidationError("staff, You don't have permission to create courses")
        
        # Validate instructor
        instructor = data.get('instructor')
        if instructor and instructor.role not in ['tutor', 'admin', 'super_admin', 'staff']:
            raise serializers.ValidationError({"instructor": "Instructor must be a tutor, admin, super_admin, or staff"})
        
        return data
    
    def create(self, validated_data):
        # Remove file fields before creating instance
        thumbnail_file = validated_data.pop('thumbnail_file', None)
        preview_video_file = validated_data.pop('preview_video_file', None)
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
       
        # Upload thumbnail to Cloudinary if provided
        if thumbnail_file:
            result = upload(
                thumbnail_file,
                folder='course_thumbnails',
                public_id=f'course_{course.id}_thumb',
                overwrite=True
            )
            course.thumbnail = result['secure_url']
        
        # Upload preview video to Cloudinary if provided
        if preview_video_file:
            result = upload(
                preview_video_file,
                folder='course_previews',
                public_id=f'course_{course.id}_preview',
                resource_type='video',
                overwrite=True
            )
            course.preview_video = result['secure_url']
        
        course.save()
        
        return course
    
    def update(self, instance, validated_data):
        # Remove file fields before updating other attributes
        thumbnail_file = validated_data.pop('thumbnail_file', None)
        preview_video_file = validated_data.pop('preview_video_file', None)
        
        # Update regular fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        # Upload new thumbnail if provided
        if thumbnail_file:
            result = upload(
                thumbnail_file,
                folder='course_thumbnails',
                public_id=f'course_{instance.id}_thumb',
                overwrite=True
            )
            instance.thumbnail = result['secure_url']
        
        # Upload new preview video if provided
        if preview_video_file:
            result = upload(
                preview_video_file,
                folder='course_previews',
                public_id=f'course_{instance.id}_preview',
                resource_type='video',
                overwrite=True
            )
            instance.preview_video = result['secure_url']
        
        instance.save()
        return instance


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


class EnrollmentWithCourseSerializer(serializers.ModelSerializer):
    """Enrollment serializer with nested course data for student views"""
    course = CourseListSerializer(read_only=True)

    class Meta:
        model = CourseEnrollment
        fields = [
            'id', 'course', 'status',
            'progress_percentage', 'completed_modules',
            'total_modules_at_enrollment',
            'enrolled_at', 'completed_at', 'last_accessed_at',
            'certificate_issued', 'certificate_url'
        ]
        read_only_fields = fields


class StudentAssessmentSerializer(serializers.ModelSerializer):
    student_email = serializers.EmailField(source='student.email', read_only=True)
    student_name = serializers.CharField(source='student.student_profile.full_name', read_only=True)
    assessment_title = serializers.CharField(source='assessment.title', read_only=True)
    assessment_type = serializers.CharField(source='assessment.assessment_type', read_only=True)
    feedback_by_name = serializers.SerializerMethodField()
    can_view_results = serializers.SerializerMethodField()
    
    class Meta:
        model = StudentAssessment
        fields = [
            'id', 'student', 'student_email', 'student_name',
            'assessment', 'assessment_title', 'assessment_type',
            'score', 'passed', 'answers', 'status',
            'submission_file', 'submission_text',
            'feedback', 'feedback_by', 'feedback_by_name', 'feedback_at', 'graded_by', 'graded_at',
            'tab_switch_count', 'last_tab_switch_at',
            'started_at', 'submitted_at', 'time_taken_minutes',
            'attempt_number', 'can_view_results'
        ]
        read_only_fields = ['id', 'started_at', 'feedback_at', 'graded_at']

    def get_feedback_by_name(self, obj):
        if not obj.feedback_by:
            return None
        profile = getattr(obj.feedback_by, 'tutor_profile', None)
        if profile and getattr(profile, 'full_name', None):
            return profile.full_name
        return getattr(obj.feedback_by, 'email', None)
    
    def get_can_view_results(self, obj):
        """Students can only see quiz results after end time or submission"""
        assessment = obj.assessment
        
        if assessment.assessment_type == 'quiz':
            # Show results after end time or if submitted
            if obj.status == 'submitted':
                if assessment.end_datetime and timezone.now() >= assessment.end_datetime:
                    return True
                if not assessment.end_datetime:
                    return True
            return False
        
        # For exams, show after submission or grading
        if assessment.assessment_type == 'exam':
            return obj.status in ['submitted', 'graded']
        
        # For assignments, always show after submission or grading
        return obj.status in ['graded', 'submitted']
    

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
    # Make course read-only since it's set from URL
    course = serializers.PrimaryKeyRelatedField(read_only=True)
    
    class Meta:
        model = CourseAnnouncement
        fields = [
            'id', 'course', 'title', 'content',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'course', 'created_by', 'created_by_name', 'created_at', 'updated_at']


class CoursePaymentSerializer(serializers.ModelSerializer):
    student_email = serializers.EmailField(source='student.email', read_only=True)
    student_name = serializers.SerializerMethodField()
    
    def get_student_name(self, obj):
        if hasattr(obj.student, 'student_profile') and obj.student.student_profile.full_name:
            return obj.student.student_profile.full_name
        return obj.student.email.split('@')[0]
    course_title = serializers.CharField(source='course.title', read_only=True)
    confirmed_by_name = serializers.SerializerMethodField()
    payment_proof = serializers.CharField(required=False, allow_null=True)
    
    def get_confirmed_by_name(self, obj):
        if obj.confirmed_by:
            return obj.confirmed_by.email
        return None
    
    class Meta:
        model = CoursePayment
        fields = [
            'id', 'student', 'student_email', 'student_name',
            'course', 'course_title', 'amount', 'payment_method',
            'status', 'transaction_id', 'payment_proof',
            'confirmed_by', 'confirmed_by_name', 'confirmed_at',
            'rejection_reason', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'student', 'amount', 'status', 'confirmed_by', 
            'confirmed_by_name', 'confirmed_at', 'created_at', 'updated_at'
        ]


class TutorNoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = TutorNote
        fields = ['id', 'teaching_notes', 'performance_observations', 'next_session_prep', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class AttendanceSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    student_email = serializers.EmailField(source='student.email', read_only=True)
    marked_by_name = serializers.CharField(source='marked_by.email', read_only=True, default=None)

    def get_student_name(self, obj):
        if hasattr(obj.student, 'student_profile') and obj.student.student_profile and obj.student.student_profile.full_name:
            return obj.student.student_profile.full_name
        return obj.student.email.split('@')[0]

    class Meta:
        model = Attendance
        fields = [
            'id', 'session', 'student', 'student_name', 'student_email',
            'status', 'marked_by', 'marked_by_name', 'marked_at', 'notes'
        ]
        read_only_fields = ['id', 'marked_by', 'marked_by_name', 'marked_at']


class LiveSessionSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    student_attendance = serializers.SerializerMethodField()
    tutor_note = TutorNoteSerializer(read_only=True)
    attendance_count = serializers.SerializerMethodField()

    def get_status(self, obj):
        return obj.get_status()

    def get_student_attendance(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated or request.user.role != 'student':
            return None
        attendance = obj.attendances.filter(student=request.user).first()
        if attendance:
            return {'status': attendance.status, 'notes': attendance.notes}
        return None

    def get_attendance_count(self, obj):
        return {
            'present': obj.attendances.filter(status='present').count(),
            'absent': obj.attendances.filter(status='absent').count(),
            'late': obj.attendances.filter(status='late').count(),
            'excused': obj.attendances.filter(status='excused').count(),
        }

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        session_status = instance.get_status()
        # Hide meet link for upcoming sessions (not started) for students
        if request and request.user.is_authenticated and request.user.role == 'student':
            if session_status == 'upcoming':
                data['meet_link'] = None
        return data

    class Meta:
        model = LiveSession
        fields = [
            'id', 'course', 'day_number', 'title', 'date',
            'start_time', 'end_time', 'meet_link', 'summary',
            'topics_covered', 'homework', 'recording_link',
            'is_completed', 'status', 'student_attendance',
            'attendance_count', 'tutor_note', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'course', 'status', 'student_attendance', 'attendance_count', 'created_at', 'updated_at']
