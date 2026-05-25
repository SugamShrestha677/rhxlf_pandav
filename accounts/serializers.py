from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.utils.crypto import get_random_string
from .models import (
    User, AdminProfile, StaffProfile, TutorProfile,
    CompanyProfile, StudentProfile, StaffPermission, AuditLog
)
import random
import string


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
        """Validate organization email uniqueness including soft-deleted users"""
        email = value.lower()
        
        # Check if email exists with any user (including soft-deleted)
        existing_user = User.objects.filter(email=email).first()
        
        if existing_user:
            if existing_user.is_deleted:
                raise serializers.ValidationError(
                    f"A user with this email was previously deactivated. "
                    f"Please restore the existing account or use a different email."
                )
            else:
                raise serializers.ValidationError("A user with this organization email already exists.")
        
        return email
    
    def validate_personal_email(self, value):
        """Personal email doesn't need to be unique"""
        return value.lower() if value else None
    
    def validate(self, data):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            raise serializers.ValidationError("Authentication required to create users.")
        
        creator = request.user
        creator_is_super_admin = creator.is_super_admin or creator.role == 'super_admin'
        target_role = data['role']
        
        # Super admin can create anyone including other admins and super admins
        if creator_is_super_admin:
            if target_role not in ['super_admin', 'admin', 'staff', 'tutor', 'company', 'student']:
                raise serializers.ValidationError({"role": "Invalid role."})
        
        # Regular admin can create all EXCEPT other admins
        elif creator.role == 'admin' and not creator_is_super_admin:
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
                raise serializers.ValidationError({"role": "Staff cannot create admin users."})
            
            if target_role not in ['tutor', 'company', 'student']:
                raise serializers.ValidationError(
                    {"role": "Staff can only create tutors, companies, or students."}
                )
        
        else:
            raise serializers.ValidationError({"role": "You don't have permission to create users."})
        
        return data
    
    def create(self, validated_data):
        # Generate a random temporary password (plain text for email)
        temp_password_plain = self._generate_temp_password()
        
        creator = self.context['request'].user
        
        # Create user manually to ensure full control
        user = User(
            email=validated_data['email'],
            personal_email=validated_data.get('personal_email'),
            role=validated_data['role'],
            is_super_admin=(validated_data['role'] == 'super_admin'),
            is_superuser=(validated_data['role'] == 'super_admin'),
            is_staff=(validated_data['role'] in ['admin', 'super_admin']),
            created_by=creator,
            is_active=True,
            must_change_password=True,  # Force True
        )
        
        # Set the temp password as the main password (hashed)
        user.set_password(temp_password_plain)
        
        # Store the HASHED temp password for verification
        user.temp_password = make_password(temp_password_plain)
        
        # Save to database
        user.save()
        
        print(f"✅ User created: {user.email}")
        print(f"   Password set (hashed): {user.password[:30]}...")
        print(f"   Temp password (hashed): {user.temp_password[:30]}...")
        print(f"   must_change_password: {user.must_change_password}")
        
        # Store plain text temp password ONLY for email (not saved to DB)
        user._temp_password = temp_password_plain
        
        # Log the creation
        AuditLog.objects.create(
            user=user,
            performed_by=creator,
            action='USER_CREATED',
            description=f"User created - Org: {user.email}, Personal: {user.personal_email}",
            metadata={
                'role': user.get_role_display(),
                'personal_email': user.personal_email,
                'creator': creator.email
            },
            ip_address=self.get_client_ip()
        )
        
        return user
    
    def _generate_temp_password(self, length=14):
        """Generate a secure random temporary password"""
        lowercase = random.choice(string.ascii_lowercase)
        uppercase = random.choice(string.ascii_uppercase)
        digit = random.choice(string.digits)
        special = random.choice('!@#$%^&*')
        
        remaining = length - 4
        all_chars = string.ascii_letters + string.digits + '!@#$%^&*'
        filler = ''.join(random.choices(all_chars, k=remaining))
        
        password_list = list(lowercase + uppercase + digit + special + filler)
        random.shuffle(password_list)
        
        return ''.join(password_list)
    
    def get_client_ip(self):
        request = self.context.get('request')
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0]
        return request.META.get('REMOTE_ADDR')


class RegisterSerializer(serializers.ModelSerializer):
    """Serializer for public self-registration (Students/Companies)"""
    first_name = serializers.CharField(required=True, write_only=True)
    last_name = serializers.CharField(required=True, write_only=True)
    company_name = serializers.CharField(required=False, allow_blank=True, write_only=True)
    password = serializers.CharField(
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

    class Meta:
        model = User
        fields = ['email', 'password', 'confirm_password', 'role', 'first_name', 'last_name', 'company_name']
        extra_kwargs = {
            'email': {'required': True},
            'role': {'required': True}
        }

    def validate_role(self, value):
        if value not in ['student', 'company']:
            raise serializers.ValidationError("Only student and company registration is allowed.")
        return value

    def validate_email(self, value):
        if User.objects.filter(email=value.lower()).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()

    def validate(self, data):
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        
        if data['role'] == 'company' and not data.get('company_name'):
            raise serializers.ValidationError({"company_name": "Company name is required for company registration."})
            
        return data

    def create(self, validated_data):
        validated_data.pop('confirm_password')
        first_name = validated_data.pop('first_name')
        last_name = validated_data.pop('last_name')
        company_name = validated_data.pop('company_name', None)
        
        # Create user
        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            role=validated_data['role'],
            must_change_password=False, # Public registration doesn't need mandatory change
            is_active=True
        )

        # Update profile with names
        profile = user.get_profile()
        if profile:
            if user.role == 'student':
                profile.full_name = f"{first_name} {last_name}".strip()
            elif user.role == 'company':
                profile.company_name = company_name
                profile.contact_person = f"{first_name} {last_name}".strip()
            profile.save()

        return user


class FirstLoginPasswordSerializer(serializers.Serializer):
    """Serializer for first-time password change (token-based flow)"""
    
    new_password = serializers.CharField(
        required=True,
        write_only=True,
        validators=[validate_password],
        style={'input_type': 'password'},
        help_text="Your new permanent password"
    )
    confirm_password = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'},
        help_text="Confirm your new password"
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
            'can_manage_students', 'can_manage_tutors',
            'can_manage_companies', 'can_manage_payments',
            'can_manage_settings', 'can_view_analytics',
            'course_scope'
        ]


class UserListSerializer(serializers.ModelSerializer):
    """Serializer for listing users - excludes soft-deleted"""
    created_by_email = serializers.EmailField(source='created_by.email', read_only=True)
    is_deleted = serializers.BooleanField(read_only=True)
    deleted_at = serializers.DateTimeField(read_only=True)
    deleted_by_email = serializers.EmailField(source='deleted_by.email', read_only=True)
    
    class Meta:
        model = User
        fields = [
            'id', 'email', 'personal_email', 'role', 'is_active',
            'must_change_password', 'profile_completed', 'created_by_email',
            'created_at', 'updated_at', 'is_deleted', 'deleted_at', 'deleted_by_email'
        ]


class UserDetailSerializer(serializers.ModelSerializer):
    """Serializer for user details with profile - includes soft delete info"""
    profile = serializers.SerializerMethodField()
    created_by_email = serializers.EmailField(source='created_by.email', read_only=True)
    deleted_by_email = serializers.EmailField(source='deleted_by.email', read_only=True)
    
    class Meta:
        model = User
        fields = [
            'id', 'email', 'personal_email', 'role', 'is_active',
            'must_change_password', 'profile_completed', 'created_by_email',
            'created_at', 'updated_at', 'profile', 'is_deleted', 
            'deleted_at', 'deleted_by_email'
        ]
        read_only_fields = ['id', 'email', 'role', 'created_at', 'updated_at']


    def get_profile(self, obj):
        profile = obj.get_profile()
        if not profile:
            return None
        
        if obj.role == 'student':
            return StudentProfileSerializer(profile).data
        elif obj.role == 'tutor':
            return TutorProfileSerializer(profile).data
        elif obj.role == 'company':
            return CompanyProfileSerializer(profile).data
        elif obj.role == 'staff':
            return StaffProfileSerializer(profile, context=self.context).data
        elif obj.role in ['admin', 'super_admin']:
            return AdminProfileSerializer(profile).data
        return None


class AuditLogSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)
    performed_by_email = serializers.EmailField(source='performed_by.email', read_only=True)
    action_display = serializers.CharField(source='get_action_display', read_only=True)
    
    class Meta:
        model = AuditLog
        fields = [
            'id', 'user', 'user_email', 'performed_by', 'performed_by_email',
            'action', 'action_display', 'description', 'metadata',
            'ip_address', 'created_at'
        ]

class SoftDeleteUserSerializer(serializers.Serializer):
    """Serializer for soft deleting users"""
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text="Reason for deactivating the user"
    )
    
    def validate(self, data):
        request = self.context.get('request')
        user = self.context.get('user')
        
        if not request or not request.user.is_authenticated:
            raise serializers.ValidationError("Authentication required.")
        
        # Prevent self-deletion
        if request.user == user:
            raise serializers.ValidationError("You cannot delete your own account.")
        
        # Super admin specific checks
        if user.is_super_admin:
            if not request.user.is_super_admin:
                raise serializers.ValidationError("Only super admin can delete other super admins.")
        
        # Admin specific checks
        if user.role == 'admin' and not user.is_super_admin:
            if not request.user.is_super_admin:
                raise serializers.ValidationError("Only super admin can delete admin users.")
        
        return data


class RestoreUserSerializer(serializers.Serializer):
    """Serializer for restoring soft-deleted users"""
    pass