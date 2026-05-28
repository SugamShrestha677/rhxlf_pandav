from django.db import models
from django.conf import settings
from django.utils import timezone


class Category(models.Model):
    """Course categories"""
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    icon_url = models.URLField(max_length=500, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'course_categories'
        verbose_name = 'Category'
        verbose_name_plural = 'Categories'
        ordering = ['name']
    
    def __str__(self):
        return self.name


class Course(models.Model):
    """Main course model"""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('archived', 'Archived'),
    ]
    LEVEL_CHOICES = [
        ('beginner', 'Beginner'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
    ]
    
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    description = models.TextField()
    short_description = models.CharField(max_length=500, blank=True, null=True)
    
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='courses')
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default='beginner')
    
    duration_weeks = models.IntegerField(default=4)
    total_hours = models.IntegerField(default=20)
    
    thumbnail = models.URLField(max_length=500, blank=True, null=True)
    preview_video = models.URLField(max_length=500, blank=True, null=True)
    
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    is_free = models.BooleanField(default=False)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    enrollment_deadline = models.DateField(null=True, blank=True)
    
    max_students = models.IntegerField(default=50)
    enrolled_count = models.IntegerField(default=0)
    course_type = models.CharField(
        max_length=20,
        choices=[('self_paced', 'Self-Paced'), ('live', 'Live Session')],
        default='self_paced'
    )
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='courses_created')
    instructor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='courses_teaching')
    
    prerequisites = models.TextField(blank=True, null=True)
    target_audience = models.TextField(blank=True, null=True)
    learning_outcomes = models.JSONField(default=list, blank=True)
    
    # SCORM fields
    is_scorm = models.BooleanField(default=False)
    scorm_course_id = models.CharField(max_length=100, blank=True, null=True)
    scorm_import_job_id = models.CharField(max_length=100, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)
    
    # Soft delete fields
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deleted_courses'
    )
    
    class Meta:
        db_table = 'courses'
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['instructor', 'status']),
            models.Index(fields=['category']),
            models.Index(fields=['is_scorm']),
            models.Index(fields=['course_type']),
        ]
        verbose_name = 'Course'
        verbose_name_plural = 'Courses'
        ordering = ['-created_at']
    
    def __str__(self):
        return self.title
    
    @property
    def total_modules(self):
        return self.modules.count()
    
    @property
    def total_contents(self):
        return ModuleContent.objects.filter(module__course=self).count()
    
    @property
    def total_quizzes(self):
        return self.assessments.filter(assessment_type='quiz').count()
    
    def publish(self):
        self.status = 'published'
        self.published_at = timezone.now()
        self.save()
    
    def archive(self):
        self.status = 'archived'
        self.save()


class CourseModule(models.Model):
    """Course modules/sections"""
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='modules')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    order_number = models.IntegerField()
    duration_minutes = models.IntegerField(default=30)
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'course_modules'
        verbose_name = 'Course Module'
        verbose_name_plural = 'Course Modules'
        ordering = ['order_number']
        unique_together = ['course', 'order_number']
    
    def __str__(self):
        return f"{self.course.title} - {self.title}"
    
    @property
    def total_contents(self):
        return self.contents.count()


class ModuleContent(models.Model):
    """Content within a module"""
    CONTENT_TYPE_CHOICES = [
        ('pdf', 'PDF Document'),
        ('mp4', 'MP4 Video'),
        ('mp3', 'MP3 Audio'),
        ('video', 'Video'),
        ('text', 'Text/Article'),
        ('quiz', 'Quiz'),
        ('assignment', 'Assignment'),
        ('link', 'External Link'),
        ('scorm', 'SCORM Package'),
    ]
    
    module = models.ForeignKey(CourseModule, on_delete=models.CASCADE, related_name='contents')
    title = models.CharField(max_length=255)
    content_type = models.CharField(max_length=20, choices=CONTENT_TYPE_CHOICES)
    description = models.TextField(blank=True, null=True)
    
    # Standard URLs (can be Cloudinary or SCORM Cloud launch links)
    file_url = models.URLField(max_length=500, blank=True, null=True)
    video_url = models.URLField(max_length=500, blank=True, null=True)
    audio_url = models.URLField(max_length=500, blank=True, null=True)
    external_link = models.URLField(max_length=500, blank=True, null=True)
    body_text = models.TextField(blank=True, null=True)
    
    # SCORM Cloud integration fields
    scorm_course_id = models.CharField(max_length=100, blank=True, null=True)
    scorm_import_job_id = models.CharField(max_length=100, blank=True, null=True)
    scorm_status = models.CharField(max_length=50, default='none') # none, uploading, processing, finished, failed
    scorm_version = models.IntegerField(default=1)
    
    order_number = models.IntegerField()
    duration_minutes = models.IntegerField(default=15, null=True, blank=True)
    is_required = models.BooleanField(default=True)
    minimum_score = models.IntegerField(default=0)
    view_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'module_contents'
        verbose_name = 'Module Content'
        verbose_name_plural = 'Module Contents'
        ordering = ['order_number']
        unique_together = ['module', 'order_number']
    
    def __str__(self):
        return f"{self.module.title} - {self.title}"


class CourseResource(models.Model):
    """Course resources - can be linked to a module or general"""
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='resources')
    module = models.ForeignKey(CourseModule, on_delete=models.SET_NULL, null=True, blank=True, related_name='resources')
    live_session = models.ForeignKey('LiveSession', on_delete=models.SET_NULL, null=True, blank=True, related_name='resources')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    
    # File can be URL (for Cloudinary upload) or just null
    file = models.URLField(max_length=500, blank=True, null=True)
    file_name = models.CharField(max_length=255, blank=True, null=True)
    file_size = models.IntegerField(default=0)
    
    # External link
    external_link = models.URLField(max_length=500, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'course_resources'
        verbose_name = 'Course Resource'
        verbose_name_plural = 'Course Resources'
        ordering = ['module__order_number', '-created_at']
    
    def __str__(self):
        return f"{self.course.title} - {self.title}"


class CourseAnnouncement(models.Model):
    """Announcements for enrolled students"""
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='announcements')
    title = models.CharField(max_length=255)
    content = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='course_announcements')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'course_announcements'
        verbose_name = 'Course Announcement'
        verbose_name_plural = 'Course Announcements'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.course.title} - {self.title}"


class Assessment(models.Model):
    """Quizzes, exams, and assignments"""
    ASSESSMENT_TYPE_CHOICES = [
        ('quiz', 'Quiz'),
        ('exam', 'Exam'),
        ('assignment', 'Assignment'),
    ]
    
    SUBMISSION_TYPE_CHOICES = [
        ('online', 'Online (in platform)'),
        ('file', 'File Upload'),
        ('text', 'Text Entry'),
        ('multiple', 'Multiple Files'),
    ]
    
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='assessments')
    module = models.ForeignKey(CourseModule, on_delete=models.CASCADE, related_name='assessments', null=True, blank=True)
    live_session = models.ForeignKey('LiveSession', on_delete=models.CASCADE, related_name='assessments', null=True, blank=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    assessment_type = models.CharField(max_length=20, choices=ASSESSMENT_TYPE_CHOICES)
    
    # Scoring
    max_score = models.DecimalField(max_digits=5, decimal_places=2, default=100.00)
    passing_score = models.DecimalField(max_digits=5, decimal_places=2, default=60.00)
    
    # Timing
    duration_minutes = models.IntegerField(default=30)
    start_datetime = models.DateTimeField(null=True, blank=True)
    end_datetime = models.DateTimeField(null=True, blank=True)
    
    # Assignment specific
    submission_type = models.CharField(max_length=20, choices=SUBMISSION_TYPE_CHOICES, default='online')
    allowed_file_types = models.CharField(max_length=255, blank=True, null=True, help_text="Comma separated: pdf,docx,zip,mp3,mp4")
    allow_late_submission = models.BooleanField(default=False)
    late_submission_deadline = models.DateTimeField(null=True, blank=True)
    max_file_size_mb = models.IntegerField(default=10)
    
    # Questions (JSON format for quiz/exam)
    questions = models.JSONField(default=list, blank=True)
    
    # Tab switching detection
    track_tab_switching = models.BooleanField(default=True)
    max_tab_switches = models.IntegerField(default=3)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def is_active(self):
        """Check if assessment is currently active"""
        now = timezone.localtime()
        if self.start_datetime and now < self.start_datetime:
            return False
        if self.end_datetime and now > self.end_datetime:
            return False
        return True
    
    def time_remaining_minutes(self):
        """Get remaining time in minutes"""
        if not self.end_datetime:
            return None
        now = timezone.localtime()
        if now > self.end_datetime:
            return 0
        delta = self.end_datetime - now
        return max(0, int(delta.total_seconds() / 60))
    
    class Meta:
        db_table = 'assessments'
        verbose_name = 'Assessment'
        verbose_name_plural = 'Assessments'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.course.title} - {self.title}"


class StudentAssessment(models.Model):
    """Student assessment attempts"""
    STATUS_CHOICES = [
        ('started', 'Started'),
        ('in_progress', 'In Progress'),
        ('submitted', 'Submitted'),
        ('graded', 'Graded'),
        ('auto_submitted', 'Auto Submitted'),
        ('expired', 'Expired'),
    ]
    
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='assessment_attempts')
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name='student_attempts')
    
    score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    passed = models.BooleanField(default=False)
    answers = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='started')
    
    # For file upload assignments
    submission_file = models.URLField(max_length=500, blank=True, null=True)
    submission_text = models.TextField(blank=True, null=True)
    
    # Tutor feedback
    feedback = models.TextField(blank=True, null=True)
    feedback_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assessment_feedback',
    )
    feedback_at = models.DateTimeField(null=True, blank=True)
    graded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='graded_assessments')
    graded_at = models.DateTimeField(null=True, blank=True)
    
    # Tab switch tracking
    tab_switch_count = models.IntegerField(default=0)
    last_tab_switch_at = models.DateTimeField(null=True, blank=True)
    
    # Timing
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    time_taken_minutes = models.IntegerField(default=0)
    attempt_number = models.IntegerField(default=1)
    
    class Meta:
        db_table = 'student_assessments'
        verbose_name = 'Student Assessment'
        verbose_name_plural = 'Student Assessments'
        ordering = ['-submitted_at', '-started_at']
    
    def __str__(self):
        return f"{self.student.email} - {self.assessment.title}"


class CourseEnrollment(models.Model):
    """Student enrollment in courses"""
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('dropped', 'Dropped'),
    ]
    
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='enrollments')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='enrollments')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    progress_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    completed_modules = models.IntegerField(default=0)
    total_modules_at_enrollment = models.IntegerField(default=0)
    
    scorm_registration_id = models.CharField(max_length=100, blank=True, null=True)
    
    enrolled_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_accessed_at = models.DateTimeField(auto_now=True)
    
    certificate_issued = models.BooleanField(default=False)
    certificate_url = models.URLField(max_length=500, blank=True, null=True)
    
    class Meta:
        db_table = 'course_enrollments'
        unique_together = ['student', 'course']
        indexes = [
            models.Index(fields=['student', 'status']),
            models.Index(fields=['course', 'status']),
            models.Index(fields=['status']),
        ]
        verbose_name = 'Course Enrollment'
        verbose_name_plural = 'Course Enrollments'
    
    def __str__(self):
        return f"{self.student.email} - {self.course.title}"
    
    def update_progress(self):
        """Update progress percentage and completion status"""
        if self.course.is_scorm:
            # For SCORM, we primarily rely on SCORM Cloud postbacks.
            # But if we have no progress yet, we can check for any content engagement.
            print(f"DEBUG: update_progress - SCORM course detected. Current progress: {self.progress_percentage}")
            if self.progress_percentage < 1:
                has_progress = StudentContentProgress.objects.filter(enrollment_id=self.id).exists()
                print(f"DEBUG: update_progress - SCORM has_progress: {has_progress}")
                if has_progress:
                    from decimal import Decimal
                    self.progress_percentage = Decimal('1.00')
        else:
            # Basic module-based progress
            total_units = self.total_modules_at_enrollment or self.course.total_modules
            if total_units == 0:
                # Fallback to contents if no modules defined
                total_units = self.course.total_contents or 1
            
            print(f"DEBUG: update_progress - completed_modules: {self.completed_modules}, total_units: {total_units}")
            module_progress = (self.completed_modules / total_units) * 100
            
            # If still 0% but some content has progress, show at least 1% for encouragement
            if module_progress < 1:
                all_progress = StudentContentProgress.objects.filter(enrollment_id=self.id)
                progress_count = all_progress.count()
                has_any_progress = progress_count > 0
                print(f"DEBUG: update_progress - enrollment_id={self.id}, has_any_progress={has_any_progress}, count={progress_count}")
                if has_any_progress:
                    module_progress = 1.0 # Show 1% if they've started
                    print("DEBUG: update_progress - setting progress to 1.0 because of content progress")
            
            from decimal import Decimal
            self.progress_percentage = Decimal(str(round(min(100.0, float(module_progress)), 2)))
            print(f"DEBUG: update_progress - non-SCORM final result: {self.progress_percentage}%")

        if self.progress_percentage >= 100:
            self.status = 'completed'
            if not self.completed_at:
                self.completed_at = timezone.now()
        
        self.save()


class StudentModuleProgress(models.Model):
    enrollment = models.ForeignKey(CourseEnrollment, on_delete=models.CASCADE, related_name='module_progress')
    module = models.ForeignKey(CourseModule, on_delete=models.CASCADE, related_name='student_progress')
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    time_spent_minutes = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'student_module_progress'
        unique_together = ['enrollment', 'module']


class StudentContentProgress(models.Model):
    enrollment = models.ForeignKey(CourseEnrollment, on_delete=models.CASCADE, related_name='content_progress')
    content = models.ForeignKey(ModuleContent, on_delete=models.CASCADE, related_name='student_progress')
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    time_spent_minutes = models.IntegerField(default=0)
    score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    attempts = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'student_content_progress'
        unique_together = ['enrollment', 'content']


class Certificate(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='certificates')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='certificates')
    enrollment = models.OneToOneField(CourseEnrollment, on_delete=models.CASCADE, related_name='certificate')
    unique_code = models.CharField(max_length=100, unique=True)
    certificate_url = models.URLField(max_length=500)
    final_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    issued_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'certificates'
        ordering = ['-issued_at']


class CourseReview(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='course_reviews')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='reviews')
    rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)])
    review_text = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'course_reviews'
        unique_together = ['student', 'course']


class CoursePayment(models.Model):
    """Course payments and verification"""
    PAYMENT_METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('online', 'Online Payment'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending Verification'),
        ('confirmed', 'Confirmed'),
        ('rejected', 'Rejected'),
    ]
    
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='payments')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Proof of payment (for online) or reference
    transaction_id = models.CharField(max_length=100, blank=True, null=True)
    payment_proof = models.URLField(max_length=500, blank=True, null=True)
    
    # Verification info
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='confirmed_payments')
    confirmed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'course_payments'
        ordering = ['-created_at']
        
    def __str__(self):
        return f"{self.student.email} - {self.course.title} ({self.status})"


class LiveSession(models.Model):
    """Live class sessions for live-type courses"""
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='live_sessions')
    day_number = models.IntegerField()
    title = models.CharField(max_length=255)
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    meet_link = models.URLField(max_length=500, blank=True, null=True)
    summary = models.TextField(blank=True, null=True)
    topics_covered = models.TextField(blank=True, null=True)
    homework = models.TextField(blank=True, null=True)
    recording_link = models.URLField(max_length=500, blank=True, null=True)
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'live_sessions'
        verbose_name = 'Live Session'
        verbose_name_plural = 'Live Sessions'
        ordering = ['day_number']
        unique_together = ['course', 'day_number']

    def __str__(self):
        return f"{self.course.title} - Day {self.day_number}: {self.title}"

    def get_status(self):
        from datetime import datetime, date
        now = timezone.localtime(timezone.now())
        session_dt_start = timezone.make_aware(
            datetime.combine(self.date, self.start_time)
        )
        session_dt_end = timezone.make_aware(
            datetime.combine(self.date, self.end_time)
        )
        from datetime import timedelta
        if not self.is_completed and now > session_dt_end + timedelta(minutes=10):
            self.is_completed = True
            self.save(update_fields=['is_completed'])
            
        if self.is_completed:
            return 'completed'
        elif now < session_dt_start:
            return 'upcoming'
        elif session_dt_start <= now <= session_dt_end + timedelta(minutes=10):
            return 'active'
        else:
            return 'completed'


class Attendance(models.Model):
    """Attendance records for live sessions"""
    STATUS_CHOICES = [
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('late', 'Late'),
        ('excused', 'Excused'),
    ]
    session = models.ForeignKey(LiveSession, on_delete=models.CASCADE, related_name='attendances')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='attendances')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='absent')
    marked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='marked_attendances')
    marked_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'attendances'
        verbose_name = 'Attendance'
        verbose_name_plural = 'Attendances'
        unique_together = ['session', 'student']

    def __str__(self):
        return f"{self.student.email} - {self.session} ({self.status})"


class TutorNote(models.Model):
    """Private tutor notes for a live session"""
    session = models.OneToOneField(LiveSession, on_delete=models.CASCADE, related_name='tutor_note')
    teaching_notes = models.TextField(blank=True, null=True)
    performance_observations = models.TextField(blank=True, null=True)
    next_session_prep = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tutor_notes'

    def __str__(self):
        return f"Notes for {self.session}"
