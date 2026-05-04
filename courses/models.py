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
        db_table = 'categories'
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
    
    # Basic Info
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    description = models.TextField()
    short_description = models.CharField(max_length=500, blank=True, null=True)
    
    # Category
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='courses'
    )
    
    # Course Details
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default='beginner')
    duration_weeks = models.IntegerField(default=4, help_text="Duration in weeks")
    total_hours = models.IntegerField(default=20, help_text="Total learning hours")
    
    # Media
    thumbnail_url = models.URLField(max_length=500, blank=True, null=True)
    preview_video_url = models.URLField(max_length=500, blank=True, null=True)
    
    # Pricing
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    is_free = models.BooleanField(default=False)
    
    # Status & Dates
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    enrollment_deadline = models.DateField(null=True, blank=True)
    
    # Capacity
    max_students = models.IntegerField(default=50)
    enrolled_count = models.IntegerField(default=0)
    
    # Creator & Instructor
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='courses_created'
    )
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='courses_teaching'
    )
    
    # Requirements
    prerequisites = models.TextField(blank=True, null=True, help_text="Course prerequisites")
    target_audience = models.TextField(blank=True, null=True)
    
    # Learning Outcomes
    learning_outcomes = models.JSONField(default=list, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'courses'
        verbose_name = 'Course'
        verbose_name_plural = 'Courses'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['instructor', 'status']),
            models.Index(fields=['slug']),
        ]
    
    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"
    
    @property
    def total_modules(self):
        return self.modules.count()
    
    @property
    def total_contents(self):
        return ModuleContent.objects.filter(module__course=self).count()
    
    @property
    def total_quizzes(self):
        return Assessment.objects.filter(course=self, assessment_type='quiz').count()
    
    def publish(self):
        self.status = 'published'
        self.published_at = timezone.now()
        self.save()
    
    def archive(self):
        self.status = 'archived'
        self.save()


class CourseModule(models.Model):
    """Course modules/sections"""
    
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='modules'
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    order_number = models.IntegerField()
    duration_minutes = models.IntegerField(default=30, help_text="Estimated duration in minutes")
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
        return f"{self.course.title} - Module {self.order_number}: {self.title}"
    
    @property
    def total_contents(self):
        return self.contents.count()


class ModuleContent(models.Model):
    """Content within a module (videos, PDFs, text, quizzes)"""
    
    CONTENT_TYPE_CHOICES = [
        ('video', 'Video'),
        ('pdf', 'PDF Document'),
        ('text', 'Text/Article'),
        ('quiz', 'Quiz'),
        ('assignment', 'Assignment'),
        ('link', 'External Link'),
    ]
    
    module = models.ForeignKey(
        CourseModule,
        on_delete=models.CASCADE,
        related_name='contents'
    )
    title = models.CharField(max_length=255)
    content_type = models.CharField(max_length=20, choices=CONTENT_TYPE_CHOICES)
    description = models.TextField(blank=True, null=True)
    
    # Content URLs/Files
    file_url = models.URLField(max_length=500, blank=True, null=True)
    video_url = models.URLField(max_length=500, blank=True, null=True)
    external_link = models.URLField(max_length=500, blank=True, null=True)
    
    # Text content
    body_text = models.TextField(blank=True, null=True)
    
    # Order & Duration
    order_number = models.IntegerField()
    duration_minutes = models.IntegerField(default=15)
    
    # Requirements
    is_required = models.BooleanField(default=True)
    minimum_score = models.IntegerField(default=0, help_text="Minimum score to pass (for quizzes)")
    
    # Tracking
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
        return f"{self.module.title} - {self.title} ({self.get_content_type_display()})"


class CourseEnrollment(models.Model):
    """Student enrollment in courses"""
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('dropped', 'Dropped'),
        ('on_hold', 'On Hold'),
    ]
    
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='enrollments'
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='enrollments'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    # Progress
    progress_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    completed_modules = models.IntegerField(default=0)
    total_modules_at_enrollment = models.IntegerField(default=0)
    
    # Dates
    enrolled_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_accessed_at = models.DateTimeField(auto_now=True)
    
    # Certificate
    certificate_issued = models.BooleanField(default=False)
    certificate_url = models.URLField(max_length=500, blank=True, null=True)
    
    class Meta:
        db_table = 'course_enrollments'
        verbose_name = 'Course Enrollment'
        verbose_name_plural = 'Course Enrollments'
        unique_together = ['student', 'course']
        indexes = [
            models.Index(fields=['student', 'status']),
            models.Index(fields=['course', 'status']),
        ]
    
    def __str__(self):
        return f"{self.student.email} - {self.course.title} ({self.get_status_display()})"
    
    def update_progress(self):
        """Calculate and update progress percentage"""
        if self.total_modules_at_enrollment == 0:
            self.progress_percentage = 0
        else:
            self.progress_percentage = (self.completed_modules / self.total_modules_at_enrollment) * 100
        
        if self.progress_percentage >= 100:
            self.status = 'completed'
            self.completed_at = timezone.now()
        
        self.save()


class StudentModuleProgress(models.Model):
    """Track student progress through each module"""
    
    enrollment = models.ForeignKey(
        CourseEnrollment,
        on_delete=models.CASCADE,
        related_name='module_progress'
    )
    module = models.ForeignKey(
        CourseModule,
        on_delete=models.CASCADE,
        related_name='student_progress'
    )
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    time_spent_minutes = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'student_module_progress'
        verbose_name = 'Student Module Progress'
        verbose_name_plural = 'Student Module Progress'
        unique_together = ['enrollment', 'module']
    
    def __str__(self):
        return f"{self.enrollment.student.email} - {self.module.title}"


class StudentContentProgress(models.Model):
    """Track student progress through each content item"""
    
    enrollment = models.ForeignKey(
        CourseEnrollment,
        on_delete=models.CASCADE,
        related_name='content_progress'
    )
    content = models.ForeignKey(
        ModuleContent,
        on_delete=models.CASCADE,
        related_name='student_progress'
    )
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    time_spent_minutes = models.IntegerField(default=0)
    
    # For quizzes/assignments
    score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    attempts = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'student_content_progress'
        verbose_name = 'Student Content Progress'
        verbose_name_plural = 'Student Content Progress'
        unique_together = ['enrollment', 'content']
    
    def __str__(self):
        return f"{self.enrollment.student.email} - {self.content.title}"


class Assessment(models.Model):
    """Quizzes and exams for courses"""
    
    ASSESSMENT_TYPE_CHOICES = [
        ('quiz', 'Quiz'),
        ('exam', 'Exam'),
        ('assignment', 'Assignment'),
    ]
    
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='assessments'
    )
    module = models.ForeignKey(
        CourseModule,
        on_delete=models.CASCADE,
        related_name='assessments',
        null=True,
        blank=True
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    assessment_type = models.CharField(max_length=20, choices=ASSESSMENT_TYPE_CHOICES)
    
    # Scoring
    max_score = models.DecimalField(max_digits=5, decimal_places=2, default=100.00)
    passing_score = models.DecimalField(max_digits=5, decimal_places=2, default=60.00)
    
    # Timing
    duration_minutes = models.IntegerField(default=30)
    
    # Questions (JSON format)
    questions = models.JSONField(default=list)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'assessments'
        verbose_name = 'Assessment'
        verbose_name_plural = 'Assessments'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.course.title} - {self.title} ({self.get_assessment_type_display()})"


class StudentAssessment(models.Model):
    """Student assessment attempts and results"""
    
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='assessment_attempts'
    )
    assessment = models.ForeignKey(
        Assessment,
        on_delete=models.CASCADE,
        related_name='student_attempts'
    )
    
    # Score
    score = models.DecimalField(max_digits=5, decimal_places=2)
    passed = models.BooleanField(default=False)
    
    # Answers
    answers = models.JSONField(default=dict)
    
    # Timing
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    time_taken_minutes = models.IntegerField(default=0)
    
    # Attempt number
    attempt_number = models.IntegerField(default=1)
    
    class Meta:
        db_table = 'student_assessments'
        verbose_name = 'Student Assessment'
        verbose_name_plural = 'Student Assessments'
        ordering = ['-submitted_at']
    
    def __str__(self):
        return f"{self.student.email} - {self.assessment.title} (Score: {self.score})"


class Certificate(models.Model):
    """Certificates issued to students"""
    
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='certificates'
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='certificates'
    )
    enrollment = models.OneToOneField(
        CourseEnrollment,
        on_delete=models.CASCADE,
        related_name='certificate'
    )
    
    # Certificate Details
    unique_code = models.CharField(max_length=100, unique=True)
    certificate_url = models.URLField(max_length=500)
    
    # Score
    final_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    
    # Dates
    issued_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'certificates'
        verbose_name = 'Certificate'
        verbose_name_plural = 'Certificates'
        ordering = ['-issued_at']
    
    def __str__(self):
        return f"{self.student.email} - {self.course.title} Certificate"


class CourseReview(models.Model):
    """Course reviews by students"""
    
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='course_reviews'
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='reviews'
    )
    
    # Rating
    rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)])
    review_text = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'course_reviews'
        verbose_name = 'Course Review'
        verbose_name_plural = 'Course Reviews'
        unique_together = ['student', 'course']
    
    def __str__(self):
        return f"{self.student.email} - {self.course.title} ({self.rating}★)"


class CourseAnnouncement(models.Model):
    """Announcements for enrolled students"""
    
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='announcements'
    )
    title = models.CharField(max_length=255)
    content = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='course_announcements'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'course_announcements'
        verbose_name = 'Course Announcement'
        verbose_name_plural = 'Course Announcements'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.course.title} - {self.title}"