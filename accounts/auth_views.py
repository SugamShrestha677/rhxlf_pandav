from django.contrib.auth import authenticate
from django.utils import timezone
from django.core.mail import send_mail, EmailMessage
from django.conf import settings
from rest_framework import status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError

from .models import User, AuditLog
from .serializers import (
    CreateUserSerializer, LoginSerializer, FirstLoginPasswordSerializer,
    ChangePasswordSerializer, ForgotPasswordSerializer, ResetPasswordSerializer
)
from .permissions import CanManageUsers

import logging

logger = logging.getLogger(__name__)


def get_tokens_for_user(user):
    """Generate JWT tokens for user"""
    refresh = RefreshToken.for_user(user)
    refresh['role'] = user.role
    refresh['email'] = user.email
    refresh['is_super_admin'] = user.is_super_admin
    
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }


def get_client_ip(request):
    """Get client IP address"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    return request.META.get('REMOTE_ADDR')


def send_credentials_email(user, temp_password):
    """
    Send welcome email with credentials to user's PERSONAL email.
    """
    try:
        recipient_email = user.notification_email
        subject = f'Welcome to Leapfrog Connect - Your Account Credentials'
        
        html_message = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #4CAF50; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }}
                .content {{ background-color: #f9f9f9; padding: 30px; border: 1px solid #ddd; }}
                .credentials-box {{ background-color: #fff; border: 2px solid #4CAF50; border-radius: 5px; padding: 20px; margin: 20px 0; }}
                .temp-password {{ background-color: #ffeb3b; padding: 5px 10px; border-radius: 3px; font-family: monospace; font-size: 16px; }}
                .warning {{ background-color: #fff3cd; border: 1px solid #ffc107; padding: 15px; border-radius: 5px; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Welcome to Leapfrog Connect! 🎉</h1>
                </div>
                <div class="content">
                    <p>Hello,</p>
                    <p>Your account has been created as a <strong>{user.get_role_display()}</strong>.</p>
                    
                    <div class="credentials-box">
                        <h3>📋 Your Login Credentials:</h3>
                        <p><strong>Organization Email (Login):</strong><br>{user.email}</p>
                        <p><strong>Temporary Password:</strong><br><span class="temp-password">{temp_password}</span></p>
                    </div>
                    
                    <div class="warning">
                        <strong>⚠️ Important:</strong> You must change your password on first login.
                    </div>
                    
                    <p><strong>Login URL:</strong> <a href="http://localhost:3000/login">http://localhost:3000/login</a></p>
                    <p>Created by: {user.created_by.email if user.created_by else 'System'}</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        plain_message = f"""
        Welcome to Leapfrog Connect!
        
        Your account has been created.
        
        Organization Email (Login): {user.email}
        Temporary Password: {temp_password}
        Role: {user.get_role_display()}
        
        You must change your password on first login.
        Login URL: http://localhost:3000/login
        """
        
        # Send email
        email_sent = send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=html_message,
            fail_silently=False,
        )
        
        logger.info(f"Credentials email sent to {recipient_email} - Success: {email_sent}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send credentials email: {str(e)}")
        return False


class CreateUserView(APIView):
    """Create user endpoint (admin/staff only)"""
    permission_classes = [permissions.IsAuthenticated, CanManageUsers]
    
    def post(self, request):
        serializer = CreateUserSerializer(
            data=request.data,
            context={'request': request}
        )
        
        if serializer.is_valid():
            user = serializer.save()
            temp_password = user._temp_password
            
            # Send credentials to personal email
            email_sent, error = send_credentials_email(user, temp_password)
            
            response_data = {
                'message': 'User created successfully',
                'user': {
                    'id': user.id,
                    'email': user.email,  # Organization email
                    'personal_email': user.personal_email,
                    'role': user.role,
                    'must_change_password': user.must_change_password,
                },
                'email_status': {
                    'sent_to': user.notification_email,
                    'success': email_sent
                }
            }
            
            if not email_sent:
                response_data['warning'] = (
                    f'User created but credentials email could not be sent to {user.personal_email}. '
                    'Please provide credentials manually.'
                )
                if error:
                    response_data['error_detail'] = error
                return Response(response_data, status=status.HTTP_201_CREATED)
            
            response_data['email_status']['message'] = f'Credentials sent to {user.personal_email}'
            return Response(response_data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class FirstLoginView(APIView):
    """First login - user must change temporary password"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        user = request.user
        
        if not user.must_change_password:
            return Response(
                {'error': 'Password change not required. Use regular change password endpoint.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = FirstLoginPasswordSerializer(data=request.data)
        
        if serializer.is_valid():
            new_password = serializer.validated_data['new_password']
            
            user.set_password(new_password)
            user.must_change_password = False
            user.temp_password = None
            user.save()
            
            AuditLog.objects.create(
                user=user,
                action='TEMP_PASSWORD_CHANGED',
                description='Temporary password changed on first login',
                ip_address=get_client_ip(request)
            )
            
            # Send confirmation email to personal email
            self.send_password_change_confirmation(user)
            
            # Generate new tokens (invalidate old ones)
            tokens = get_tokens_for_user(user)
            
            return Response({
                'message': 'Password set successfully! You can now use the platform.',
                'tokens': tokens
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def send_password_change_confirmation(self, user):
        """Send confirmation that password was changed"""
        try:
            subject = 'Password Successfully Changed - Leapfrog Connect'
            message = f"""
            Hello,
            
            Your temporary password has been successfully changed.
            
            Organization Email: {user.email}
            Role: {user.get_role_display()}
            
            If you did not make this change, please contact your administrator immediately.
            
            Leapfrog Connect Platform
            """
            
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.notification_email],
                fail_silently=True,
            )
        except Exception as e:
            logger.error(f"Failed to send password change confirmation: {str(e)}")


class LoginView(APIView):
    """User login - uses organization email"""
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        
        if serializer.is_valid():
            email = serializer.validated_data['email'].lower()
            password = serializer.validated_data['password']
            
            user = authenticate(request, email=email, password=password)
            
            if user:
                if not user.is_active:
                    AuditLog.objects.create(
                        user=user,
                        action='LOGIN_FAILED',
                        description='Login attempt on deactivated account',
                        ip_address=get_client_ip(request)
                    )
                    return Response(
                        {'error': 'Account is deactivated. Contact your administrator.'},
                        status=status.HTTP_403_FORBIDDEN
                    )
                
                user.last_login = timezone.now()
                user.last_login_ip = get_client_ip(request)
                user.save()
                
                tokens = get_tokens_for_user(user)
                
                AuditLog.objects.create(
                    user=user,
                    action='LOGIN_SUCCESS',
                    description='Successful login',
                    ip_address=get_client_ip(request)
                )
                
                return Response({
                    'message': 'Login successful',
                    'user': {
                        'id': user.id,
                        'email': user.email,
                        'personal_email': user.personal_email,
                        'role': user.role,
                        'must_change_password': user.must_change_password,
                        'profile_completed': user.profile_completed,
                    },
                    'tokens': tokens,
                    'redirect_to': '/set-password/' if user.must_change_password else '/dashboard/'
                })
            
            AuditLog.objects.create(
                action='LOGIN_FAILED',
                description=f'Failed login attempt for {email}',
                metadata={'email': email},
                ip_address=get_client_ip(request)
            )
            
            return Response(
                {'error': 'Invalid credentials'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LogoutView(APIView):
    """User logout"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
            
            return Response(
                {'message': 'Logout successful'},
                status=status.HTTP_200_OK
            )
        except TokenError:
            return Response(
                {'error': 'Invalid token'},
                status=status.HTTP_400_BAD_REQUEST
            )


class ForgotPasswordView(APIView):
    """Forgot password - sends reset link to personal email"""
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        
        if serializer.is_valid():
            email = serializer.validated_data['email'].lower()
            
            try:
                user = User.objects.get(email=email, is_active=True)
                
                token = get_random_string(64)
                user.password_reset_token = token
                user.password_reset_expires = timezone.now() + timezone.timedelta(hours=24)
                user.save()
                
                # Send reset link to personal email
                self.send_reset_email(user, token)
                
                return Response({
                    'message': 'If the account exists, a password reset link has been sent to your personal email.'
                })
                
            except User.DoesNotExist:
                pass
            
            return Response({
                'message': 'If the account exists, a password reset link has been sent to your personal email.'
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def send_reset_email(self, user, token):
        """Send password reset link to personal email"""
        try:
            subject = 'Password Reset Request - Leapfrog Connect'
            reset_url = f"http://localhost:3000/reset-password?token={token}"
            
            html_message = f"""
            <html>
            <body style="font-family: Arial, sans-serif; padding: 20px;">
                <h2>Password Reset Request</h2>
                <p>You requested a password reset for your account:</p>
                <p><strong>Organization Email:</strong> {user.email}</p>
                <p><strong>Role:</strong> {user.get_role_display()}</p>
                <p>Click the button below to reset your password:</p>
                <p>
                    <a href="{reset_url}" 
                       style="background-color: #4CAF50; color: white; padding: 10px 20px; 
                              text-decoration: none; border-radius: 5px; display: inline-block;">
                        Reset Password
                    </a>
                </p>
                <p>This link expires in 24 hours.</p>
                <p>If you did not request this, please ignore this email.</p>
            </body>
            </html>
            """
            
            send_mail(
                subject=subject,
                message=f"Reset your password: {reset_url}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.notification_email],
                html_message=html_message,
                fail_silently=False,
            )
            
            logger.info(f"Password reset email sent to {user.notification_email}")
            
        except Exception as e:
            logger.error(f"Failed to send reset email: {str(e)}")


class ResetPasswordView(APIView):
    """Reset password with token"""
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        
        if serializer.is_valid():
            token = serializer.validated_data['token']
            
            try:
                user = User.objects.get(
                    password_reset_token=token,
                    password_reset_expires__gt=timezone.now()
                )
                
                user.set_password(serializer.validated_data['new_password'])
                user.must_change_password = False
                user.password_reset_token = None
                user.password_reset_expires = None
                user.save()
                
                AuditLog.objects.create(
                    user=user,
                    action='PASSWORD_CHANGED',
                    description='Password reset via forgot password',
                    ip_address=get_client_ip(request)
                )
                
                return Response({
                    'message': 'Password reset successful. You can now login with your new password.'
                })
                
            except User.DoesNotExist:
                return Response(
                    {'error': 'Invalid or expired reset token'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ChangePasswordView(APIView):
    """Change password for authenticated users"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        
        if serializer.is_valid():
            user = request.user
            
            if not user.check_password(serializer.validated_data['old_password']):
                return Response(
                    {'error': 'Current password is incorrect'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            user.set_password(serializer.validated_data['new_password'])
            user.save()
            
            AuditLog.objects.create(
                user=user,
                action='PASSWORD_CHANGED',
                description='Password changed by user',
                ip_address=get_client_ip(request)
            )
            
            return Response({
                'message': 'Password changed successfully'
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)