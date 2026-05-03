from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from .auth_views import (
    CreateUserView, LoginView, LogoutView,
    FirstLoginView, ForgotPasswordView, 
    ResetPasswordView, ChangePasswordView
)
from .views import UserViewSet, StaffPermissionViewSet, AuditLogViewSet

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='users')
router.register(r'staff-permissions', StaffPermissionViewSet, basename='staff-permissions')
router.register(r'audit-logs', AuditLogViewSet, basename='audit-logs')

urlpatterns = [
    # User creation and authentication
    path('auth/users/create-user', CreateUserView.as_view(), name='create-user'),
    path('auth/login', LoginView.as_view(), name='login'),
    path('auth/logout', LogoutView.as_view(), name='logout'),
    path('auth/token/refresh', TokenRefreshView.as_view(), name='token-refresh'),
    
    # Password management
    path('auth/first-login', FirstLoginView.as_view(), name='first-login'),
    path('auth/change-password', ChangePasswordView.as_view(), name='change-password'),
    path('auth/forgot-password', ForgotPasswordView.as_view(), name='forgot-password'),
    path('auth/reset-password', ResetPasswordView.as_view(), name='reset-password'),
    
    # Router URLs
    path('', include(router.urls)),
]