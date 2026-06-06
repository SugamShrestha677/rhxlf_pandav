from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone
from django.utils.crypto import get_random_string


class UserManager(BaseUserManager):
    """Custom user manager for role-based system"""
    
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Organization Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_password(get_random_string(12))
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """
        Create the FIRST super admin only.
        This should ONLY be used via management command.
        """
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)  # Only for the initial super admin
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('role', 'admin')
        extra_fields.setdefault('must_change_password', False)
        extra_fields.setdefault('is_super_admin', True)  # Custom flag for our system
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        
        return self.create_user(email, password, **extra_fields)
    
    def create_admin(self, email, password=None, **extra_fields):
        """
        Create regular admin - NO superuser privileges.
        This is used when super admin creates another admin.
        """
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', False)  # Regular admin
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('role', 'admin')
        extra_fields.setdefault('must_change_password', True)
        extra_fields.setdefault('is_super_admin', False)  # Not super admin
        
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Custom User model with role-based hierarchy and dual emails"""
    
    ROLE_CHOICES = [
        ('super_admin', 'Super Admin'),
        ('admin', 'Admin'),
        ('staff', 'Staff'),
        ('tutor', 'Tutor'),
        ('company', 'Company'),
        ('student', 'Student'),
    ]
    
    # Organization Email - Used for all platform activities
    email = models.EmailField(
        unique=True, 
        db_index=True,
        help_text="Organization email - Used for login and all platform activities"
    )
    
    # Personal Email - Where credentials are sent
    personal_email = models.EmailField(
        null=True,
        blank=True,
        help_text="Personal email - Where credentials and notifications are sent"
    )
    
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, db_index=True)
    
    # Custom flag for our system's super admin (different from Django's is_superuser)
    is_super_admin = models.BooleanField(
        default=False,
        help_text="Designates whether this user is the platform super admin"
    )
    
    # Status flags
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)  # Django admin access
    
    # Password management
    must_change_password = models.BooleanField(default=True)
    temp_password = models.CharField(max_length=128, blank=True, null=True)
    
    # Hierarchy tracking
    created_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_users'
    )
    
    # Profile completion tracking
    profile_completed = models.BooleanField(default=False)
    
    # Password reset
    password_reset_token = models.CharField(max_length=100, blank=True, null=True)
    password_reset_expires = models.DateTimeField(blank=True, null=True)

    # Soft delete fields
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deleted_users'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    
    objects = UserManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []
    
    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.email} ({self.get_role_display()})"
    
    @property
    def notification_email(self):
        """Get the email for sending notifications"""
        return self.personal_email or self.email
    
    def is_role(self, role):
        """Check if user has specific role"""
        return self.role == role
    
    def can_manage_users(self):
        """Check if user can create/manage other users"""
        # Super admin can do everything
        if self.is_super_admin:
            return True
        
        # Regular admin can manage users
        if self.role == 'admin':
            return True
        
        # Staff with permission
        if self.role == 'staff':
            return (
                hasattr(self, 'staff_profile') and 
                hasattr(self.staff_profile, 'permissions') and
                self.staff_profile.permissions.can_create_users
            )
        
        return False
    
    def can_create_admins(self):
        """Only super admin can create other admins"""
        return self.is_super_admin
    
    def get_profile(self):
        """Get the role-specific profile"""
        profile_map = {
            'student': 'student_profile',
            'tutor': 'tutor_profile',
            'company': 'company_profile',
            'staff': 'staff_profile',
            'admin': 'admin_profile',
            'super_admin': 'admin_profile',
        }
        profile_attr = profile_map.get(self.role)
        if profile_attr:
            return getattr(self, profile_attr, None)
        return None

class AdminProfile(models.Model):
    """Admin-specific profile information"""
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='admin_profile'
    )
    full_name = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    profile_picture_url = models.URLField(max_length=500, blank=True, null=True)
    department = models.CharField(max_length=100, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'admin_profiles'
        verbose_name = 'Admin Profile'
        verbose_name_plural = 'Admin Profiles'
    
    def __str__(self):
        return f"{self.full_name or 'Admin'} - {self.user.email}"


class StaffProfile(models.Model):
    """Staff-specific profile information"""
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='staff_profile'
    )
    full_name = models.CharField(max_length=255, blank=True, null=True)
    department = models.CharField(max_length=100, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    profile_picture_url = models.URLField(max_length=500, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'staff_profiles'
        verbose_name = 'Staff Profile'
        verbose_name_plural = 'Staff Profiles'
    
    def __str__(self):
        return f"{self.full_name or 'Staff'} - {self.user.email}"


class TutorProfile(models.Model):
    """Tutor-specific profile information"""
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='tutor_profile'
    )
    full_name = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    bio = models.TextField(blank=True, null=True)
    expertise_summary = models.TextField(blank=True, null=True)
    profile_picture_url = models.URLField(max_length=500, blank=True, null=True)
    linkedin_url = models.URLField(max_length=500, blank=True, null=True)
    years_of_experience = models.IntegerField(default=0)
    qualification = models.CharField(max_length=255, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'tutor_profiles'
        verbose_name = 'Tutor Profile'
        verbose_name_plural = 'Tutor Profiles'
    
    def __str__(self):
        return f"{self.full_name or 'Tutor'} - {self.user.email}"


class CompanyProfile(models.Model):
    """Company-specific profile information"""
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='company_profile'
    )
    company_name = models.CharField(max_length=255, blank=True, null=True)
    industry = models.CharField(max_length=100, blank=True, null=True)
    website = models.URLField(max_length=500, blank=True, null=True)
    logo_url = models.URLField(max_length=500, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    company_size = models.CharField(max_length=50, blank=True, null=True)
    location = models.CharField(max_length=255, blank=True, null=True)
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    contact_person = models.CharField(max_length=255, blank=True, null=True)
    contact_email = models.EmailField(blank=True, null=True)
    contact_phone = models.CharField(max_length=20, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'company_profiles'
        verbose_name = 'Company Profile'
        verbose_name_plural = 'Company Profiles'
    
    def __str__(self):
        return f"{self.company_name or 'Company'} - {self.user.email}"


class StudentProfile(models.Model):
    """Student-specific profile information"""
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='student_profile'
    )
    full_name = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    date_of_birth = models.DateField(null=True, blank=True)
    bio = models.TextField(blank=True, null=True)
    cv_file_url = models.URLField(max_length=500, blank=True, null=True)
    portfolio_url = models.URLField(max_length=500, blank=True, null=True)
    linkedin_url = models.URLField(max_length=500, blank=True, null=True)
    github_url = models.URLField(max_length=500, blank=True, null=True)
    profile_picture_url = models.URLField(max_length=500, blank=True, null=True)
    is_in_talent_pool = models.BooleanField(default=False)
    talent_pool_opted_at = models.DateTimeField(null=True, blank=True)
    profile_strength = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'student_profiles'
        verbose_name = 'Student Profile'
        verbose_name_plural = 'Student Profiles'
    
    def __str__(self):
        return f"{self.full_name or 'Student'} - {self.user.email}"


class StaffPermission(models.Model):
    """Staff-specific permissions"""
    
    staff = models.OneToOneField(
        StaffProfile,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='permissions'
    )
    can_create_users = models.BooleanField(default=False)
    can_manage_courses = models.BooleanField(default=False)
    can_manage_students = models.BooleanField(default=False)
    can_manage_tutors = models.BooleanField(default=False)
    can_manage_companies = models.BooleanField(default=False)
    can_manage_payments = models.BooleanField(default=False)
    can_manage_settings = models.BooleanField(default=False)
    can_view_analytics = models.BooleanField(default=False)
    course_scope = models.CharField(
        max_length=20,
        choices=[('all', 'All Courses'), ('assigned', 'Assigned Only')],
        default='assigned'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'staff_permissions'
        verbose_name = 'Staff Permission'
        verbose_name_plural = 'Staff Permissions'
    
    def __str__(self):
        return f"Permissions for {self.staff.full_name or 'Staff'}"


class AuditLog(models.Model):
    """Audit trail for important actions"""
    
    ACTION_CHOICES = [
        ('USER_CREATED', 'User Created'),
        ('USER_UPDATED', 'User Updated'),
        ('USER_DEACTIVATED', 'User Deactivated'),
        ('USER_ACTIVATED', 'User Activated'),
        ('ROLE_CHANGED', 'Role Changed'),
        ('PERMISSION_GRANTED', 'Permission Granted'),
        ('LOGIN_SUCCESS', 'Login Success'),
        ('LOGIN_FAILED', 'Login Failed'),
        ('PASSWORD_CHANGED', 'Password Changed'),
        ('TEMP_PASSWORD_CHANGED', 'Temporary Password Changed'),
        ('PROFILE_UPDATED', 'Profile Updated'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='audit_logs')
    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='performed_actions'
    )
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    description = models.TextField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'audit_logs'
        verbose_name = 'Audit Log'
        verbose_name_plural = 'Audit Logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['action', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.action} - {self.user} at {self.created_at}"


class Notification(models.Model):
    """In-app notifications for users"""
    
    NOTIFICATION_TYPES = [
        ('course_enrollment', 'Course Enrollment'),
        ('course_completion', 'Course Completion'),
        ('assignment_graded', 'Assignment Graded'),
        ('quiz_graded', 'Quiz Graded'),
        ('system_alert', 'System Alert'),
        ('message', 'Message'),
        ('attendance_alert', 'Attendance Alert'),
        ('certificate_available', 'Certificate Available'),
        ('general', 'General'),
    ]
    
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=255)
    message = models.TextField()
    notification_type = models.CharField(max_length=50, choices=NOTIFICATION_TYPES, default='general')
    link = models.URLField(max_length=500, blank=True, null=True)
    is_read = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'notifications'
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', '-created_at']),
            models.Index(fields=['recipient', 'is_read']),
        ]
        
    def __str__(self):
        return f"{self.notification_type} for {self.recipient.email}"