from rest_framework import status, permissions, viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from django.db import models as db_models

from LMS.api import api_error, api_success

from .models import User, StaffPermission, AuditLog
from .serializers import (
    UserDetailSerializer, UserListSerializer,
    AdminProfileSerializer, StaffProfileSerializer,
    TutorProfileSerializer, CompanyProfileSerializer,
    StudentProfileSerializer, StaffPermissionSerializer, AuditLogSerializer
)
from .permissions import CanManageUsers, IsAdminOrStaff


class UserViewSet(viewsets.ModelViewSet):
    """ViewSet for managing users"""
    queryset = User.objects.all()
    
    def get_serializer_class(self):
        if self.action in ['retrieve', 'me']:
            return UserDetailSerializer
        return UserListSerializer
    
    def get_permissions(self):
        if self.action in ['create']:
            return [permissions.IsAuthenticated(), CanManageUsers()]
        elif self.action in ['list', 'destroy']:
            return [IsAdminOrStaff()]
        elif self.action == 'me':
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated()]
    
    def get_queryset(self):
        user = self.request.user
        
        if user.is_super_admin or user.role == 'super_admin':
            return User.objects.all()
            
        if user.role == 'admin':
            return User.objects.filter(
                db_models.Q(created_by=user) | db_models.Q(id=user.id)
            )
        elif user.role == 'staff':
            if hasattr(user, 'staff_profile') and hasattr(user.staff_profile, 'permissions'):
                if user.staff_profile.permissions.can_create_users:
                    return User.objects.filter(created_by=user)
            return User.objects.filter(id=user.id)
        elif user.role == 'tutor':
            return User.objects.filter(
                student_profile__courseenrollment__course__instructor=user
            ).distinct()
        elif user.role == 'company':
            return User.objects.filter(
                role='student',
                student_profile__is_in_talent_pool=True
            )
        
        return User.objects.filter(id=user.id)
    
    @action(detail=False, methods=['get', 'patch'])
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
        
        AuditLog.objects.create(
            user=user,
            action='PROFILE_UPDATED',
            description=f'Profile updated for {user.role}',
            ip_address=self.get_client_ip(request)
        )
        
        return api_success(data=serializer.data, message='Profile updated successfully')
    
    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """Deactivate a user"""
        if request.user.role not in ['admin', 'staff']:
            raise PermissionDenied("Only administrators can deactivate users")
        
        user = self.get_object()
        
        if user == request.user:
            return api_error(message='Cannot deactivate yourself', status_code=status.HTTP_400_BAD_REQUEST)
        
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
    
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Activate a user"""
        if request.user.role not in ['admin', 'staff']:
            raise PermissionDenied("Only administrators can activate users")
        
        user = self.get_object()
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
    
    @action(detail=True, methods=['post'])
    def change_role(self, request, pk=None):
        """Change user's role (admin only)"""
        if request.user.role != 'admin':
            raise PermissionDenied("Only admins can change roles")
        
        user = self.get_object()
        new_role = request.data.get('role')
        
        if not new_role or new_role not in dict(User.ROLE_CHOICES):
            return api_error(message='Invalid role', status_code=status.HTTP_400_BAD_REQUEST)
        
        old_role = user.role
        user.role = new_role
        user.save()
        
        AuditLog.objects.create(
            user=user,
            performed_by=request.user,
            action='ROLE_CHANGED',
            description=f'Role changed from {old_role} to {new_role}',
            ip_address=self.get_client_ip(request)
        )
        
        return api_success(message=f'Role changed from {old_role} to {new_role}')

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get platform-wide stats for super admin"""
        if request.user.role != 'super_admin' and not request.user.is_super_admin:
            raise PermissionDenied("Only super admins can view platform stats")
            
        from courses.models import Course, CourseEnrollment
        
        data = {
            'users': {
                'total': User.objects.count(),
                'admins': User.objects.filter(role='admin').count(),
                'students': User.objects.filter(role='student').count(),
                'tutors': User.objects.filter(role='tutor').count(),
                'companies': User.objects.filter(role='company').count(),
                'active': User.objects.filter(is_active=True).count(),
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
        if self.request.user.role != 'admin':
            raise PermissionDenied("Only administrators can view audit logs")
        return AuditLog.objects.all()


class StaffPermissionViewSet(viewsets.ModelViewSet):
    """ViewSet for managing staff permissions (admin only)"""
    queryset = StaffPermission.objects.all()
    serializer_class = StaffPermissionSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_permissions(self):
        if self.request.user.role != 'admin':
            raise PermissionDenied("Only admins can manage staff permissions")
        return super().get_permissions()
    
    def get_queryset(self):
        if self.request.user.role == 'admin':
            return StaffPermission.objects.filter(
                staff__user__created_by=self.request.user
            )
        return StaffPermission.objects.none()