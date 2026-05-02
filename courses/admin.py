from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Course, CourseModule, ModuleContent, CourseEnrollment,
    StudentModuleProgress, StudentContentProgress,
    Assessment, StudentAssessment, Certificate,
    CourseReview, CourseAnnouncement
)


class CourseModuleInline(admin.TabularInline):
    model = CourseModule
    extra = 0
    fields = ['title', 'order_number', 'duration_minutes', 'is_published']
    show_change_link = True


class AssessmentInline(admin.TabularInline):
    model = Assessment
    extra = 0
    fields = ['title', 'assessment_type', 'max_score', 'passing_score', 'duration_minutes']


class CourseEnrollmentInline(admin.TabularInline):
    model = CourseEnrollment
    extra = 0
    fields = ['student', 'status', 'progress_percentage', 'enrolled_at']
    readonly_fields = ['enrolled_at']
    show_change_link = True


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'instructor', 'level', 'status', 'price',
        'enrolled_count', 'total_modules', 'created_at', 'is_published'
    ]
    list_filter = [
        'status', 'level', 'is_free', 'created_at',
        'instructor__role'
    ]
    search_fields = ['title', 'description', 'instructor__email']
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = [
        'slug', 'enrolled_count', 'created_at', 'updated_at',
        'published_at', 'total_modules', 'total_contents', 'total_quizzes'
    ]
    
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'title', 'slug', 'description', 'short_description',
                'level', 'thumbnail_url', 'preview_video_url'
            )
        }),
        ('Course Details', {
            'fields': (
                'duration_weeks', 'total_hours', 'start_date',
                'end_date', 'enrollment_deadline', 'max_students'
            )
        }),
        ('Pricing', {
            'fields': ('price', 'is_free')
        }),
        ('Management', {
            'fields': (
                'status', 'instructor', 'created_by',
                'enrolled_count', 'published_at'
            )
        }),
        ('Requirements & Outcomes', {
            'fields': ('prerequisites', 'target_audience', 'learning_outcomes')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    inlines = [CourseModuleInline, AssessmentInline, CourseEnrollmentInline]
    
    def is_published(self, obj):
        return obj.status == 'published'
    is_published.boolean = True
    is_published.short_description = 'Published'
    
    def total_modules(self, obj):
        return obj.total_modules
    total_modules.short_description = 'Modules'
    
    actions = ['publish_courses', 'archive_courses']
    
    def publish_courses(self, request, queryset):
        updated = queryset.filter(status='draft').update(
            status='published',
            published_at=timezone.now()
        )
        self.message_user(request, f'{updated} course(s) published successfully.')
    publish_courses.short_description = "Publish selected courses"
    
    def archive_courses(self, request, queryset):
        updated = queryset.filter(status='published').update(status='archived')
        self.message_user(request, f'{updated} course(s) archived successfully.')
    archive_courses.short_description = "Archive selected courses"


class ModuleContentInline(admin.TabularInline):
    model = ModuleContent
    extra = 0
    fields = ['title', 'content_type', 'order_number', 'duration_minutes', 'is_required']


@admin.register(CourseModule)
class CourseModuleAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'course_title', 'order_number',
        'duration_minutes', 'is_published', 'content_count'
    ]
    list_filter = ['is_published', 'course__status']
    search_fields = ['title', 'course__title']
    ordering = ['course', 'order_number']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Module Information', {
            'fields': ('course', 'title', 'description')
        }),
        ('Settings', {
            'fields': ('order_number', 'duration_minutes', 'is_published')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    inlines = [ModuleContentInline]
    
    def course_title(self, obj):
        return obj.course.title
    course_title.short_description = 'Course'
    course_title.admin_order_field = 'course__title'
    
    def content_count(self, obj):
        return obj.total_contents
    content_count.short_description = 'Contents'


@admin.register(ModuleContent)
class ModuleContentAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'module_title', 'content_type',
        'order_number', 'duration_minutes', 'is_required', 'view_count'
    ]
    list_filter = ['content_type', 'is_required', 'module__course']
    search_fields = ['title', 'module__title', 'module__course__title']
    ordering = ['module__course', 'module__order_number', 'order_number']
    readonly_fields = ['view_count', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Content Information', {
            'fields': (
                'module', 'title', 'content_type', 'description'
            )
        }),
        ('Content Body', {
            'fields': (
                'file_url', 'video_url', 'external_link', 'body_text'
            ),
            'classes': ('wide',)
        }),
        ('Settings', {
            'fields': (
                'order_number', 'duration_minutes',
                'is_required', 'minimum_score'
            )
        }),
        ('Analytics', {
            'fields': ('view_count',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def module_title(self, obj):
        return obj.module.title
    module_title.short_description = 'Module'
    module_title.admin_order_field = 'module__title'


@admin.register(CourseEnrollment)
class CourseEnrollmentAdmin(admin.ModelAdmin):
    list_display = [
        'student_email', 'course_title', 'status',
        'progress_bar', 'enrolled_at', 'completed_at'
    ]
    list_filter = [
        'status', 'certificate_issued',
        'enrolled_at', 'course__title'
    ]
    search_fields = [
        'student__email', 'student__student_profile__full_name',
        'course__title'
    ]
    ordering = ['-enrolled_at']
    readonly_fields = [
        'progress_percentage', 'completed_modules',
        'total_modules_at_enrollment', 'enrolled_at',
        'completed_at', 'last_accessed_at'
    ]
    
    fieldsets = (
        ('Enrollment Details', {
            'fields': ('student', 'course', 'status')
        }),
        ('Progress', {
            'fields': (
                'progress_percentage', 'completed_modules',
                'total_modules_at_enrollment'
            )
        }),
        ('Certificate', {
            'fields': ('certificate_issued', 'certificate_url')
        }),
        ('Dates', {
            'fields': ('enrolled_at', 'completed_at', 'last_accessed_at')
        }),
    )
    
    def student_email(self, obj):
        return obj.student.email
    student_email.short_description = 'Student'
    student_email.admin_order_field = 'student__email'
    
    def course_title(self, obj):
        return obj.course.title
    course_title.short_description = 'Course'
    course_title.admin_order_field = 'course__title'
    
    def progress_bar(self, obj):
        color = 'green' if obj.progress_percentage >= 50 else 'orange'
        return format_html(
            '<div style="background-color: #f0f0f0; border-radius: 3px; padding: 2px; width: 100px;">'
            '<div style="background-color: {}; width: {}%; height: 20px; border-radius: 3px; '
            'display: flex; align-items: center; justify-content: center; color: white; '
            'font-size: 11px;">{:.0f}%</div>'
            '</div>',
            color, float(obj.progress_percentage), float(obj.progress_percentage)
        )
    progress_bar.short_description = 'Progress'
    progress_bar.allow_tags = True


@admin.register(StudentModuleProgress)
class StudentModuleProgressAdmin(admin.ModelAdmin):
    list_display = [
        'student_email', 'module_title', 'course_title',
        'is_completed', 'completed_at'
    ]
    list_filter = ['is_completed', 'completed_at']
    search_fields = [
        'enrollment__student__email',
        'module__title',
        'module__course__title'
    ]
    readonly_fields = ['time_spent_minutes']
    
    def student_email(self, obj):
        return obj.enrollment.student.email
    student_email.short_description = 'Student'
    
    def module_title(self, obj):
        return obj.module.title
    module_title.short_description = 'Module'
    
    def course_title(self, obj):
        return obj.module.course.title
    course_title.short_description = 'Course'


@admin.register(StudentContentProgress)
class StudentContentProgressAdmin(admin.ModelAdmin):
    list_display = [
        'student_email', 'content_title', 'is_completed',
        'score', 'attempts', 'completed_at'
    ]
    list_filter = ['is_completed', 'completed_at']
    search_fields = [
        'enrollment__student__email',
        'content__title'
    ]
    readonly_fields = ['time_spent_minutes']
    
    def student_email(self, obj):
        return obj.enrollment.student.email
    student_email.short_description = 'Student'
    
    def content_title(self, obj):
        return obj.content.title
    content_title.short_description = 'Content'


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'course_title', 'assessment_type',
        'max_score', 'passing_score', 'duration_minutes'
    ]
    list_filter = ['assessment_type', 'course__title']
    search_fields = ['title', 'course__title']
    ordering = ['course', '-created_at']
    readonly_fields = ['created_at', 'updated_at']
    
    def course_title(self, obj):
        return obj.course.title
    course_title.short_description = 'Course'
    course_title.admin_order_field = 'course__title'


@admin.register(StudentAssessment)
class StudentAssessmentAdmin(admin.ModelAdmin):
    list_display = [
        'student_email', 'assessment_title', 'score',
        'passed', 'attempt_number', 'submitted_at'
    ]
    list_filter = ['passed', 'attempt_number', 'submitted_at']
    search_fields = ['student__email', 'assessment__title']
    ordering = ['-submitted_at']
    readonly_fields = ['started_at', 'submitted_at']
    
    def student_email(self, obj):
        return obj.student.email
    student_email.short_description = 'Student'
    
    def assessment_title(self, obj):
        return obj.assessment.title
    assessment_title.short_description = 'Assessment'
    
    def passed_status(self, obj):
        color = 'green' if obj.passed else 'red'
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            '✓ PASSED' if obj.passed else '✗ FAILED'
        )
    passed_status.short_description = 'Result'
    passed_status.allow_tags = True


@admin.register(Certificate)
class CertificateAdmin(admin.ModelAdmin):
    list_display = [
        'student_email', 'course_title', 'unique_code',
        'final_score', 'issued_at'
    ]
    search_fields = [
        'student__email',
        'student__student_profile__full_name',
        'course__title',
        'unique_code'
    ]
    ordering = ['-issued_at']
    readonly_fields = ['unique_code', 'issued_at']
    
    def student_email(self, obj):
        return obj.student.email
    student_email.short_description = 'Student'
    
    def course_title(self, obj):
        return obj.course.title
    course_title.short_description = 'Course'


@admin.register(CourseReview)
class CourseReviewAdmin(admin.ModelAdmin):
    list_display = [
        'student_email', 'course_title', 'rating_stars',
        'created_at'
    ]
    list_filter = ['rating', 'created_at']
    search_fields = ['student__email', 'course__title', 'review_text']
    ordering = ['-created_at']
    
    def student_email(self, obj):
        return obj.student.email
    student_email.short_description = 'Student'
    
    def course_title(self, obj):
        return obj.course.title
    course_title.short_description = 'Course'
    
    def rating_stars(self, obj):
        stars = '★' * obj.rating + '☆' * (5 - obj.rating)
        return format_html(
            '<span style="color: #FFD700; font-size: 16px;">{}</span>',
            stars
        )
    rating_stars.short_description = 'Rating'


@admin.register(CourseAnnouncement)
class CourseAnnouncementAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'course_title', 'created_by_email',
        'created_at'
    ]
    list_filter = ['created_at', 'course__title']
    search_fields = ['title', 'content', 'course__title']
    ordering = ['-created_at']
    
    def course_title(self, obj):
        return obj.course.title
    course_title.short_description = 'Course'
    
    def created_by_email(self, obj):
        return obj.created_by.email
    created_by_email.short_description = 'Created By'