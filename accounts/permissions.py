from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied


class CanManageUsers(permissions.BasePermission):
    """Permission for users who can create/manage other users"""
    
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        
        user = request.user
        
        # Super admin can manage all users
        if user.is_super_admin or user.role == 'super_admin':
            return True
        
        # Regular admin can manage users
        if user.role == 'admin':
            return True
        
        # Staff with permission
        if user.role == 'staff':
            return (
                hasattr(user, 'staff_profile') and 
                hasattr(user.staff_profile, 'permissions') and 
                user.staff_profile.permissions.can_create_users
            )
        
        return False


class IsSuperAdmin(permissions.BasePermission):
    """Permission for super admin only"""
    
    def has_permission(self, request, view):
        return request.user.is_authenticated and (request.user.is_super_admin or request.user.role == 'super_admin')


class IsAdminOrStaff(permissions.BasePermission):
    """
    Permission class that allows access to admin, super_admin, and staff users
    """
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Allow super_admin, admin, and staff
        return request.user.role in ['admin', 'super_admin'] or request.user.is_staff
    
    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class IsAdmin(permissions.BasePermission):
    """Permission for admin (including super admin)"""
    
    def has_permission(self, request, view):
        return request.user.is_authenticated and (request.user.role == 'admin' or request.user.is_super_admin)