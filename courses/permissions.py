from rest_framework import permissions


class CanManageCourses(permissions.BasePermission):
    """Permission to create/manage courses"""
    
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        
        user = request.user
        
        # Admin can manage all courses
        if user.role == 'admin':
            return True
        
        # Tutor can manage their own courses
        if user.role == 'tutor':
            return True
        
        # Staff with permission
        if user.role == 'staff':
            return (
                hasattr(user, 'staff_profile') and
                hasattr(user.staff_profile, 'permissions') and
                user.staff_profile.permissions.can_manage_courses
            )
        
        return False


class IsCourseInstructor(permissions.BasePermission):
    """Permission for course instructor"""
    
    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False
        
        # Admin can access all
        if request.user.role == 'admin':
            return True
        
        # Check if user is the course instructor
        if hasattr(obj, 'instructor') and obj.instructor == request.user:
            return True
        
        # Check if obj is a course
        if hasattr(obj, 'course'):
            return obj.course.instructor == request.user
        
        return False


class IsEnrolledStudent(permissions.BasePermission):
    """Permission for enrolled students"""
    
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'student'


class IsStudentOwner(permissions.BasePermission):
    """Permission for student's own data"""
    
    def has_object_permission(self, request, view, obj):
        if hasattr(obj, 'student') and obj.student == request.user:
            return True
        if hasattr(obj, 'enrollment') and obj.enrollment.student == request.user:
            return True
        return False