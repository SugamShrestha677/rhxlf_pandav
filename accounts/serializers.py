from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.utils.crypto import get_random_string
from .models import (
    User, AdminProfile, StaffProfile, TutorProfile,
    CompanyProfile, StudentProfile, StaffPermission, AuditLog
)


class CreateUserSerializer(serializers.ModelSerializer):
    """Serializer for admin/staff to create users with dual emails"""
    
    class Meta:
        model = User
        fields = ['email', 'personal_email', 'role']
        extra_kwargs = {
            'email': {'required': True, 'help_text': 'Organization email for login'},
            'personal_email': {'required': True, 'help_text': 'Personal email for receiving credentials'},
            'role': {'required': True}
        }
    
    def validate_email(self, value):
        """Validate organization email uniqueness"""
        if User.objects.filter(email=value.lower()).exists():
            raise serializers.ValidationError("A user with this organization email already exists.")
        return value.lower()
    
    def validate_personal_email(self, value):
        """Personal email doesn't need to be unique"""
        return value.lower() if value else None
    
    def validate(self, data):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            raise serializers.ValidationError("Authentication required to create users.")
        
        creator = request.user
        target_role = data['role']
        
        # Super admin can create anyone including other admins
        if creator.is_super_admin:
            if target_role not in ['admin', 'staff', 'tutor', 'company', 'student']:
                raise serializers.ValidationError(
                    {"role": "Invalid role."}
                )
        
        # Regular admin can create all EXCEPT other admins
        elif creator.role == 'admin' and not creator.is_super_admin:
            if target_role == 'admin':
                raise serializers.ValidationError(
                    {"role": "Only super admin can create other admins."}
                )
            if target_role not in ['staff', 'tutor', 'company', 'student']:
                raise serializers.ValidationError(
                    {"role": "Admin can only create staff, tutors, companies, or students."}
                )
        
        # Staff can create only if permitted
        elif creator.role == 'staff':
            if not hasattr(creator, 'staff_profile') or not hasattr(creator.staff_profile, 'permissions'):
                raise serializers.ValidationError({"role": "Staff profile or permissions not found."})
            
            if not creator.staff_profile.permissions.can_create_users:
                raise serializers.ValidationError({"role": "You don't have permission to create users."})
            
            if target_role == 'admin':
                raise serializers.ValidationError(
                    {"role": "Staff cannot create admin users."}
                )
            
            if target_role not in ['tutor', 'company', 'student']:
                raise serializers.ValidationError(
                    {"role": "Staff can only create tutors, companies, or students."}
                )
        
        else:
            raise serializers.ValidationError({"role": "You don't have permission to create users."})
        
        return data
    
    def create(self, validated_data):
        # Generate random temporary password
        import random
        import string
        temp_password = ''.join(random.choices(string.ascii_letters + string.digits + '!@#$%^&*', k=12))
        
        # Determine if this user should be super admin (only for admin role created by super admin)
        is_super_admin = False
        creator = self.context['request'].user
        
        # Create user with temp password
        user = User.objects.create_user(
            email=validated_data['email'],
            password=temp_password,
            personal_email=validated_data.get('personal_email'),
            role=validated_data['role'],
            must_change_password=True,
            is_super_admin=is_super_admin,  # Never super admin when created by anyone
            is_superuser=False,  # Django's superuser flag
            is_staff=(validated_data['role'] == 'admin'),  # Only admins get staff access
            created_by=creator
        )
        
        # Store temp password for email
        user.temp_password = temp_password
        user.save()
        
        # Create empty profile
        profile_map = {
            'admin': AdminProfile,
            'staff': StaffProfile,
            'tutor': TutorProfile,
            'company': CompanyProfile,
            'student': StudentProfile,
        }
        
        ProfileModel = profile_map.get(user.role)
        if ProfileModel:
            profile = ProfileModel.objects.create(user=user)
            
            # Create staff permissions if staff
            if user.role == 'staff':
                StaffPermission.objects.create(staff=profile)
        
        # Log creation
        AuditLog.objects.create(
            user=user,
            performed_by=creator,
            action='USER_CREATED',
            description=f"User created - Org email: {user.email}, Personal email: {user.personal_email}",
            metadata={
                'role': user.get_role_display(),
                'personal_email': user.personal_email,
                'creator': creator.email
            },
            ip_address=self.get_client_ip()
        )
        
        # Attach temp password for email
        user._temp_password = temp_password
        
        return user
    
    def get_client_ip(self):
        request = self.context.get('request')
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0]
        return request.META.get('REMOTE_ADDR')


class FirstLoginPasswordSerializer(serializers.Serializer):
    """Serializer for first-time password change"""
    
    new_password = serializers.CharField(
        required=True,
        write_only=True,
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    confirm_password = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'}
    )
    
    def validate(self, data):
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError(
                {"confirm_password": "Passwords do not match."}
            )
        return data


class LoginSerializer(serializers.Serializer):
    """Serializer for user login - uses organization email"""
    email = serializers.EmailField(
        required=True,
        help_text="Organization email for login"
    )
    password = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'}
    )


class ChangePasswordSerializer(serializers.Serializer):
    """Serializer for changing password"""
    old_password = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'}
    )
    new_password = serializers.CharField(
        required=True,
        write_only=True,
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    confirm_password = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'}
    )
    
    def validate(self, data):
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError(
                {"confirm_password": "New passwords do not match."}
            )
        return data


class ForgotPasswordSerializer(serializers.Serializer):
    """Forgot password - uses organization email"""
    email = serializers.EmailField(
        required=True,
        help_text="Organization email for password reset"
    )


class ResetPasswordSerializer(serializers.Serializer):
    """Reset password with token"""
    token = serializers.CharField(required=True)
    new_password = serializers.CharField(
        required=True,
        write_only=True,
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    confirm_password = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'}
    )
    
    def validate(self, data):
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError(
                {"confirm_password": "New passwords do not match."}
            )
        return data


# ==================== Profile Update Serializers ====================

class AdminProfileSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source='user.email', read_only=True)
    personal_email = serializers.EmailField(source='user.personal_email', read_only=True)
    
    class Meta:
        model = AdminProfile
        fields = [
            'user_id', 'email', 'personal_email', 'full_name', 'phone',
            'profile_picture_url', 'department', 'created_at', 'updated_at'
        ]
        read_only_fields = ['user_id', 'email', 'personal_email', 'created_at', 'updated_at']
    
    def update(self, instance, validated_data):
        profile = super().update(instance, validated_data)
        if profile.full_name:
            profile.user.profile_completed = True
            profile.user.save()
        return profile


class StaffProfileSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source='user.email', read_only=True)
    personal_email = serializers.EmailField(source='user.personal_email', read_only=True)
    permissions = serializers.SerializerMethodField()
    
    class Meta:
        model = StaffProfile
        fields = [
            'user_id', 'email', 'personal_email', 'full_name', 'department',
            'phone', 'profile_picture_url', 'permissions',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['user_id', 'email', 'personal_email', 'created_at', 'updated_at']
    
    def get_permissions(self, obj):
        if hasattr(obj, 'permissions'):
            return StaffPermissionSerializer(obj.permissions).data
        return None
    
    def update(self, instance, validated_data):
        profile = super().update(instance, validated_data)
        if profile.full_name:
            profile.user.profile_completed = True
            profile.user.save()
        return profile


class TutorProfileSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source='user.email', read_only=True)
    personal_email = serializers.EmailField(source='user.personal_email', read_only=True)
    
    class Meta:
        model = TutorProfile
        fields = [
            'user_id', 'email', 'personal_email', 'full_name', 'phone', 'bio',
            'expertise_summary', 'profile_picture_url', 'linkedin_url',
            'years_of_experience', 'qualification', 'created_at', 'updated_at'
        ]
        read_only_fields = ['user_id', 'email', 'personal_email', 'created_at', 'updated_at']
    
    def update(self, instance, validated_data):
        profile = super().update(instance, validated_data)
        if profile.full_name:
            profile.user.profile_completed = True
            profile.user.save()
        return profile


class CompanyProfileSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source='user.email', read_only=True)
    personal_email = serializers.EmailField(source='user.personal_email', read_only=True)
    
    class Meta:
        model = CompanyProfile
        fields = [
            'user_id', 'email', 'personal_email', 'company_name', 'industry', 'website',
            'logo_url', 'description', 'company_size', 'location',
            'is_verified', 'contact_person', 'contact_email', 'contact_phone',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['user_id', 'email', 'personal_email', 'is_verified', 'created_at', 'updated_at']
    
    def update(self, instance, validated_data):
        profile = super().update(instance, validated_data)
        if profile.company_name:
            profile.user.profile_completed = True
            profile.user.save()
        return profile


class StudentProfileSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source='user.email', read_only=True)
    personal_email = serializers.EmailField(source='user.personal_email', read_only=True)
    
    class Meta:
        model = StudentProfile
        fields = [
            'user_id', 'email', 'personal_email', 'full_name', 'phone', 'date_of_birth',
            'bio', 'cv_file_url', 'portfolio_url', 'linkedin_url',
            'github_url', 'profile_picture_url', 'is_in_talent_pool',
            'profile_strength', 'created_at', 'updated_at'
        ]
        read_only_fields = ['user_id', 'email', 'personal_email', 'profile_strength', 'created_at', 'updated_at']
    
    def update(self, instance, validated_data):
        profile = super().update(instance, validated_data)
        fields = [
            profile.full_name, profile.bio, profile.phone,
            profile.cv_file_url, profile.portfolio_url,
            profile.linkedin_url, profile.profile_picture_url,
            profile.date_of_birth
        ]
        completed = sum(1 for field in fields if field)
        profile.profile_strength = int((completed / len(fields)) * 100)
        profile.user.profile_completed = profile.profile_strength >= 50
        profile.user.save()
        profile.save()
        return profile


class StaffPermissionSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source='staff.full_name', read_only=True)
    staff_email = serializers.EmailField(source='staff.user.email', read_only=True)
    
    class Meta:
        model = StaffPermission
        fields = [
            'staff_name', 'staff_email',
            'can_create_users', 'can_manage_courses',
            'can_view_analytics', 'course_scope'
        ]


class UserDetailSerializer(serializers.ModelSerializer):
    """Serializer for user details with profile"""
    profile = serializers.SerializerMethodField()
    created_by_email = serializers.EmailField(source='created_by.email', read_only=True)
    
    class Meta:
        model = User
        fields = [
            'id', 'email', 'personal_email', 'role', 'is_active',
            'must_change_password', 'profile_completed', 'created_by_email',
            'created_at', 'updated_at', 'profile'
        ]
        read_only_fields = ['id', 'email', 'role', 'created_at', 'updated_at']
    
    def get_profile(self, obj):
        profile = obj.get_profile()
        if not profile:
            return None
        
        serializer_map = {
            'admin': AdminProfileSerializer,
            'staff': StaffProfileSerializer,
            'tutor': TutorProfileSerializer,
            'company': CompanyProfileSerializer,
            'student': StudentProfileSerializer,
        }
        
        SerializerClass = serializer_map.get(obj.role)
        if SerializerClass:
            return SerializerClass(profile).data
        return None


class UserListSerializer(serializers.ModelSerializer):
    """Serializer for listing users"""
    created_by_email = serializers.EmailField(source='created_by.email', read_only=True)
    
    class Meta:
        model = User
        fields = [
            'id', 'email', 'personal_email', 'role', 'is_active',
            'must_change_password', 'profile_completed', 'created_by_email',
            'created_at', 'updated_at'
        ]