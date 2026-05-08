# views.py - Complete fixed UserViewSet

from django.db import models as db_models
from django.utils import timezone
from rest_framework import settings, viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from django.contrib.auth.hashers import make_password

from LMS.api import api_error, api_success
from .models import StaffPermission, User, AuditLog
from .serializers import (
    UserDetailSerializer, UserListSerializer,
    AdminProfileSerializer, StaffProfileSerializer,
    TutorProfileSerializer, CompanyProfileSerializer,
    StudentProfileSerializer, StaffPermissionSerializer, AuditLogSerializer,
    CreateUserSerializer, SoftDeleteUserSerializer, RestoreUserSerializer
)
from .permissions import CanManageUsers, IsAdminOrStaff

import logging

logger = logging.getLogger(__name__)


class UserViewSet(viewsets.ModelViewSet):
    """ViewSet for managing users with soft delete support"""
    queryset = User.objects.all()
    
    def get_serializer_class(self):
        if self.action in ['retrieve', 'me']:
            return UserDetailSerializer
        return UserListSerializer
    
    def get_permissions(self):
        """
        Define permissions for different actions
        """
        if self.action == 'create_user':
            return [permissions.IsAuthenticated(), CanManageUsers()]
        elif self.action in ['list', 'deleted_users', 'stats']:
            return [permissions.IsAuthenticated(), IsAdminOrStaff()]
        elif self.action in ['soft_delete', 'restore', 'permanent_delete', 'activate', 'deactivate', 'change_role']:
            return [permissions.IsAuthenticated(), IsAdminOrStaff()]
        elif self.action == 'me':
            return [permissions.IsAuthenticated()]
        elif self.action == 'destroy':
            return [permissions.IsAuthenticated(), IsAdminOrStaff()]
        return [permissions.IsAuthenticated()]
    
    def get_queryset(self):
        user = self.request.user
        # Determine if the requesting user is an admin or super admin
        is_admin_role = getattr(user, 'is_super_admin', False) or getattr(user, 'role', None) in ['admin', 'super_admin']

        # Admins and superadmins should be able to LIST, RETRIEVE and perform
        # detail actions (soft-delete, restore, permanent delete, activate,
        # deactivate, change-role, destroy) on any user so the view can
        # load the target object for permission/validation checks.
        if getattr(self, 'action', None) in [
            'list', 'retrieve', 'soft_delete', 'restore', 'permanent_delete',
            'activate', 'deactivate', 'change_role', 'destroy'
        ] and is_admin_role:
            return User.objects.all()

        # For non-list/retrieve operations, honor include_deleted query param
        include_deleted = self.request.query_params.get('include_deleted', 'false').lower() == 'true'
        if include_deleted and is_admin_role:
            base_queryset = User.objects.all()
        else:
            base_queryset = User.objects.filter(is_deleted=False)

        # Admin-specific narrower view for non-list operations
        if user.role == 'admin':
            return base_queryset.filter(
                db_models.Q(created_by=user) |
                db_models.Q(id=user.id) |
                db_models.Q(role__in=['staff', 'tutor', 'company', 'student'])
            )

        # Staff sees only users they created (if they have permission)
        if user.role == 'staff':
            if hasattr(user, 'staff_profile') and hasattr(user.staff_profile, 'permissions'):
                if user.staff_profile.permissions.can_create_users:
                    return base_queryset.filter(created_by=user)
            return base_queryset.filter(id=user.id)

        # Other roles only see themselves
        return base_queryset.filter(id=user.id)

    def list(self, request, *args, **kwargs):
        """List users with proper filtering"""
        queryset = self.filter_queryset(self.get_queryset())
        
        # Additional filtering
        role = request.query_params.get('role')
        if role:
            queryset = queryset.filter(role=role)
        
        search = request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                db_models.Q(email__icontains=search) |
                db_models.Q(personal_email__icontains=search)
            )
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
            
        serializer = self.get_serializer(queryset, many=True)
        return api_success(data=serializer.data)
    
    def retrieve(self, request, *args, **kwargs):
        """Get a specific user"""
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return api_success(data=serializer.data)
    
    def destroy(self, request, *args, **kwargs):
        """Override destroy to use soft delete"""
        return self.soft_delete(request, *args, **kwargs)
    
    @action(detail=False, methods=['get', 'patch'], url_path='me', url_name='me')
    def me(self, request):
        """Get or update current user's profile"""
        user = request.user
        
        if request.method == 'GET':
            serializer = UserDetailSerializer(user)
            return api_success(data=serializer.data)
        
        # Update profile
        profile = user.get_profile()
        if not profile:
            return api_error(message='Profile not found', status_code=status.HTTP_404_NOT_FOUND)
        
        serializer_map = {
            'admin': AdminProfileSerializer,
            'staff': StaffProfileSerializer,
            'tutor': TutorProfileSerializer,
            'company': CompanyProfileSerializer,
            'student': StudentProfileSerializer,
        }
        
        ProfileSerializer = serializer_map.get(user.role)
        if not ProfileSerializer:
            return api_error(message=f'No profile serializer for role {user.role}', status_code=status.HTTP_400_BAD_REQUEST)
        
        serializer = ProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        # Update profile_completed flag
        if hasattr(serializer, 'validated_data') and serializer.validated_data:
            user.profile_completed = True
            user.save()
        
        AuditLog.objects.create(
            user=user,
            action='PROFILE_UPDATED',
            description=f'Profile updated for {user.role}',
            ip_address=self.get_client_ip(request)
        )
        
        return api_success(data=serializer.data, message='Profile updated successfully')
    
    @action(detail=False, methods=['post'], url_path='create', url_name='create_user')
    def create_user(self, request):
        """Create user endpoint (admin/staff only)"""
        from .auth_views import send_credentials_email
        
        serializer = CreateUserSerializer(
            data=request.data,
            context={'request': request}
        )
        
        if serializer.is_valid():
            user = serializer.save()
            temp_password_plain = user._temp_password
            
            # Send credentials to personal email
            email_sent = send_credentials_email(user, temp_password_plain)
            
            response_data = {
                'user': {
                    'id': user.id,
                    'email': user.email,
                    'personal_email': user.personal_email,
                    'role': user.role,
                    'must_change_password': user.must_change_password,
                },
                'email_sent': email_sent,
                'email_sent_to': user.notification_email if email_sent else None,
            }
            
            if not email_sent and settings.DEBUG:
                response_data['debug_temp_password'] = temp_password_plain
            
            return api_success(data=response_data, message='User created successfully', status_code=status.HTTP_201_CREATED)
        
        return api_error(message='Validation error', errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'], url_path='soft-delete', url_name='soft_delete')
    def soft_delete(self, request, pk=None):
        """Soft delete a user (mark as deleted without removing from database)"""
        user = self.get_object()
        
        # Check if already deleted
        if user.is_deleted:
            return api_error(
                message='User is already deleted.',
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if trying to delete self
        if request.user == user:
            return api_error(
                message='You cannot delete your own account.',
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate deletion permissions
        serializer = SoftDeleteUserSerializer(
            data=request.data,
            context={'request': request, 'user': user}
        )
        
        if not serializer.is_valid():
            return api_error(
                message='Validation error',
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        # Perform soft delete
        user.is_deleted = True
        user.deleted_at = timezone.now()
        user.deleted_by = request.user
        user.is_active = False  # Also deactivate the account
        user.save()
        
        # Log the deletion
        AuditLog.objects.create(
            user=user,
            performed_by=request.user,
            action='USER_SOFT_DELETED',
            description=f"User soft deleted by {request.user.email}",
            metadata={
                'reason': serializer.validated_data.get('reason', 'No reason provided'),
                'deleted_by': request.user.email,
                'deleted_at': str(user.deleted_at)
            },
            ip_address=self.get_client_ip(request)
        )
        
        return api_success(
            data={
                'id': user.id,
                'email': user.email,
                'deleted_at': user.deleted_at,
                'deleted_by': request.user.email
            },
            message=f'User {user.email} has been deactivated successfully.'
        )
    
    @action(detail=True, methods=['post'], url_path='restore', url_name='restore')
    def restore(self, request, pk=None):
        """Restore a soft-deleted user"""
        # Get user including soft-deleted ones
        try:
            user = User.objects.get(pk=pk, is_deleted=True)
        except User.DoesNotExist:
            return api_error(
                message='User not found or not deleted.',
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        # Permission checks for restoration
        requesting_user = request.user
        
        # Super admin can restore anyone
        if not requesting_user.is_super_admin:
            # Admin can restore non-admin users
            if requesting_user.role == 'admin':
                if user.role == 'admin' or user.is_super_admin:
                    return api_error(
                        message='Only super admin can restore admin or super admin users.',
                        status_code=status.HTTP_403_FORBIDDEN
                    )
            else:
                # Other roles cannot restore users
                return api_error(
                    message='You do not have permission to restore users.',
                    status_code=status.HTTP_403_FORBIDDEN
                )
        
        # Perform restore
        user.is_deleted = False
        user.deleted_at = None
        user.deleted_by = None
        user.is_active = True  # Reactivate the account
        user.save()
        
        # Log the restoration
        AuditLog.objects.create(
            user=user,
            performed_by=request.user,
            action='USER_RESTORED',
            description=f"User restored by {request.user.email}",
            metadata={
                'restored_by': request.user.email,
                'restored_at': str(timezone.now())
            },
            ip_address=self.get_client_ip(request)
        )
        
        return api_success(
            data={
                'id': user.id,
                'email': user.email,
                'restored_at': timezone.now()
            },
            message=f'User {user.email} has been restored successfully.'
        )
    
    @action(detail=False, methods=['get'], url_path='deleted-users', url_name='deleted_users')
    def deleted_users(self, request):
        """List all soft-deleted users (for admin/super admin only)"""
        # Check permissions
        if request.user.role not in ['admin', 'super_admin']:
            return api_error(
                message='You do not have permission to view deleted users.',
                status_code=status.HTTP_403_FORBIDDEN
            )
        
        # Get all soft-deleted users
        deleted_users = User.objects.filter(is_deleted=True)
        
        # Additional filtering based on role
        if request.user.role == 'admin' and not request.user.is_super_admin:
            # Regular admin cannot see deleted admins or super admins
            deleted_users = deleted_users.exclude(role='admin').exclude(is_super_admin=True)
        
        # Apply search filter
        search = request.query_params.get('search')
        if search:
            deleted_users = deleted_users.filter(
                db_models.Q(email__icontains=search) |
                db_models.Q(personal_email__icontains=search)
            )
        
        # Apply role filter
        role = request.query_params.get('role')
        if role:
            deleted_users = deleted_users.filter(role=role)
        
        # Pagination
        page = self.paginate_queryset(deleted_users)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(deleted_users, many=True)
        return api_success(data=serializer.data)
    
    @action(detail=True, methods=['delete'], url_path='permanent-delete', url_name='permanent_delete')
    def permanent_delete(self, request, pk=None):
        """Permanently delete a user from database (use with caution!)"""
        # Only super admin can permanently delete
        if not request.user.is_super_admin:
            return api_error(
                message='Only super admin can permanently delete users.',
                status_code=status.HTTP_403_FORBIDDEN
            )
        
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return api_error(
                message='User not found.',
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        # Prevent self-deletion
        if request.user == user:
            return api_error(
                message='You cannot permanently delete your own account.',
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        # Log before deletion
        user_email = user.email
        user_role = user.role
        
        AuditLog.objects.create(
            user=user,
            performed_by=request.user,
            action='USER_PERMANENTLY_DELETED',
            description=f"User permanently deleted by {request.user.email}",
            metadata={
                'deleted_by': request.user.email,
                'user_email': user_email,
                'user_role': user_role
            },
            ip_address=self.get_client_ip(request)
        )
        
        # Permanently delete
        user.delete()
        
        return api_success(
            message=f'User {user_email} has been permanently deleted from the system.'
        )
    
    @action(detail=True, methods=['post'], url_path='activate', url_name='activate')
    def activate(self, request, pk=None):
        """Activate a user"""
        if request.user.role not in ['admin', 'staff', 'super_admin']:
            raise PermissionDenied("Only administrators can activate users")
        
        user = self.get_object()
        
        if user.is_deleted:
            return api_error(
                message='Cannot activate a deleted user. Please restore first.',
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        user.is_active = True
        user.save()
        
        AuditLog.objects.create(
            user=user,
            performed_by=request.user,
            action='USER_ACTIVATED',
            description=f'Account activated by {request.user.email}',
            ip_address=self.get_client_ip(request)
        )
        
        return api_success(message=f'User {user.email} activated')
    
    @action(detail=True, methods=['post'], url_path='deactivate', url_name='deactivate')
    def deactivate(self, request, pk=None):
        """Deactivate a user"""
        if request.user.role not in ['admin', 'staff', 'super_admin']:
            raise PermissionDenied("Only administrators can deactivate users")
        
        user = self.get_object()
        
        if user == request.user:
            return api_error(message='Cannot deactivate yourself', status_code=status.HTTP_400_BAD_REQUEST)
        
        if user.is_deleted:
            return api_error(
                message='Cannot deactivate a deleted user.',
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        user.is_active = False
        user.save()
        
        AuditLog.objects.create(
            user=user,
            performed_by=request.user,
            action='USER_DEACTIVATED',
            description=f'Account deactivated by {request.user.email}',
            ip_address=self.get_client_ip(request)
        )
        
        return api_success(message=f'User {user.email} deactivated')
    
    @action(detail=True, methods=['post'], url_path='change-role', url_name='change_role')
    def change_role(self, request, pk=None):
        """Change user's role (admin only)"""
        if request.user.role not in ['admin', 'super_admin']:
            raise PermissionDenied("Only admins can change roles")
        
        user = self.get_object()
        new_role = request.data.get('role')
        
        if not new_role or new_role not in dict(User.ROLE_CHOICES):
            return api_error(message='Invalid role', status_code=status.HTTP_400_BAD_REQUEST)
        
        # Prevent changing to super_admin if not super admin
        if new_role == 'super_admin' and not request.user.is_super_admin:
            return api_error(message='Only super admin can assign super admin role', status_code=status.HTTP_403_FORBIDDEN)
        
        old_role = user.role
        user.role = new_role
        
        # Update is_super_admin flag
        if new_role == 'super_admin':
            user.is_super_admin = True
            user.is_staff = True
        elif new_role == 'admin':
            user.is_super_admin = False
            user.is_staff = True
        else:
            user.is_super_admin = False
            user.is_staff = False
        
        user.save()
        
        AuditLog.objects.create(
            user=user,
            performed_by=request.user,
            action='ROLE_CHANGED',
            description=f'Role changed from {old_role} to {new_role}',
            ip_address=self.get_client_ip(request)
        )
        
        return api_success(message=f'Role changed from {old_role} to {new_role}')

    @action(detail=False, methods=['get'], url_path='stats', url_name='stats')
    def stats(self, request):
        """Get platform-wide stats for super admin"""
        if request.user.role != 'super_admin' and not request.user.is_super_admin:
            raise PermissionDenied("Only super admins can view platform stats")
            
        from courses.models import Course, CourseEnrollment
        
        data = {
            'users': {
                'total': User.objects.filter(is_deleted=False).count(),
                'total_with_deleted': User.objects.count(),
                'deleted': User.objects.filter(is_deleted=True).count(),
                'admins': User.objects.filter(role='admin', is_deleted=False).count(),
                'super_admins': User.objects.filter(role='super_admin', is_deleted=False).count(),
                'students': User.objects.filter(role='student', is_deleted=False).count(),
                'tutors': User.objects.filter(role='tutor', is_deleted=False).count(),
                'staff': User.objects.filter(role='staff', is_deleted=False).count(),
                'companies': User.objects.filter(role='company', is_deleted=False).count(),
                'active': User.objects.filter(is_active=True, is_deleted=False).count(),
            },
            'courses': {
                'total': Course.objects.count(),
                'published': Course.objects.filter(status='published').count(),
                'draft': Course.objects.filter(status='draft').count(),
            },
            'enrollments': {
                'total': CourseEnrollment.objects.count(),
                'active': CourseEnrollment.objects.filter(status='active').count(),
                'completed': CourseEnrollment.objects.filter(status='completed').count(),
            }
        }
        
        return api_success(data=data)
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0]
        return request.META.get('REMOTE_ADDR')

class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for viewing audit logs (admin only)"""
    queryset = AuditLog.objects.all()
    serializer_class = AuditLogSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        if self.request.user.role != 'admin' and not self.request.user.is_super_admin:
            raise PermissionDenied("Only administrators can view audit logs")
        return AuditLog.objects.all().order_by('-created_at')

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return api_success(data=serializer.data)


class StaffPermissionViewSet(viewsets.ModelViewSet):
    """ViewSet for managing staff permissions (admin only)"""
    queryset = StaffPermission.objects.all()
    serializer_class = StaffPermissionSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_permissions(self):
        return [permissions.IsAuthenticated()]
    
    def get_queryset(self):
        user = self.request.user
        if user.role in ['admin', 'super_admin'] or user.is_super_admin:
            return StaffPermission.objects.all()
        return StaffPermission.objects.none()