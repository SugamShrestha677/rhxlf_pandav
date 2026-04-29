from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import (
    User, AdminProfile, StaffProfile, TutorProfile,
    CompanyProfile, StudentProfile, StaffPermission, AuditLog
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['email', 'personal_email', 'role', 'is_active', 'must_change_password', 'profile_completed', 'created_at']
    list_filter = ['role', 'is_active', 'must_change_password', 'created_at']
    search_fields = ['email', 'personal_email']
    ordering = ['-created_at']
    
    fieldsets = (
        (None, {'fields': ('email', 'personal_email', 'password')}),
        ('Role & Status', {'fields': ('role', 'is_active', 'is_staff', 'is_superuser', 'must_change_password')}),
        ('Hierarchy', {'fields': ('created_by',)}),
        ('Password Reset', {'fields': ('password_reset_token', 'password_reset_expires')}),
        ('Important dates', {'fields': ('last_login', 'created_at', 'updated_at')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'personal_email', 'password1', 'password2', 'role'),
        }),
    )
    
    readonly_fields = ['created_at', 'updated_at']


@admin.register(AdminProfile)
class AdminProfileAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'user_email', 'department']
    search_fields = ['full_name', 'user__email']
    
    def user_email(self, obj):
        return obj.user.email


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'user_email', 'department']
    search_fields = ['full_name', 'user__email']
    
    def user_email(self, obj):
        return obj.user.email


@admin.register(TutorProfile)
class TutorProfileAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'user_email', 'years_of_experience']
    search_fields = ['full_name', 'user__email']
    
    def user_email(self, obj):
        return obj.user.email


@admin.register(CompanyProfile)
class CompanyProfileAdmin(admin.ModelAdmin):
    list_display = ['company_name', 'user_email', 'industry', 'is_verified']
    list_filter = ['is_verified']
    search_fields = ['company_name', 'user__email']
    
    def user_email(self, obj):
        return obj.user.email


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'user_email', 'is_in_talent_pool', 'profile_strength']
    search_fields = ['full_name', 'user__email']
    
    def user_email(self, obj):
        return obj.user.email


@admin.register(StaffPermission)
class StaffPermissionAdmin(admin.ModelAdmin):
    list_display = ['staff_name', 'can_create_users', 'can_manage_courses', 'can_view_analytics']
    list_filter = ['can_create_users', 'can_manage_courses', 'can_view_analytics']
    
    def staff_name(self, obj):
        return obj.staff.full_name


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['action', 'user_email', 'performed_by_email', 'created_at']
    list_filter = ['action', 'created_at']
    search_fields = ['user__email', 'description']
    readonly_fields = ['created_at']
    
    def user_email(self, obj):
        return obj.user.email if obj.user else None
    
    def performed_by_email(self, obj):
        return obj.performed_by.email if obj.performed_by else None