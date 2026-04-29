from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User
from .utils import generate_otp, is_otp_expired, send_otp_email


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "full_name",
            "role",
            "is_verified",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ("email", "full_name", "password", "role")
        extra_kwargs = {
            "role": {"required": False},
        }

    def validate_email(self, value):
        return value.lower().strip()

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        role = validated_data.pop("role", User.ROLE_STUDENT)
        user = User(**validated_data, role=role)
        user.set_password(password)
        otp = generate_otp()
        user.email_otp = otp
        user.otp_created_at = timezone.now()
        user.save()
        send_otp_email(user.email, user.full_name, otp, purpose="email verification")
        return user


class VerifyEmailSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(min_length=6, max_length=6)

    def validate_email(self, value):
        return value.lower().strip()

    def validate(self, attrs):
        try:
            user = User.objects.get(email=attrs["email"])
        except User.DoesNotExist as exc:
            raise serializers.ValidationError({"email": "User not found."}) from exc

        if user.is_verified:
            raise serializers.ValidationError({"email": "Email is already verified."})

        if not user.email_otp or not user.otp_created_at:
            raise serializers.ValidationError({"otp": "OTP not found. Please request a new one."})

        if is_otp_expired(user.otp_created_at):
            raise serializers.ValidationError({"otp": "OTP has expired. Please request a new one."})

        if user.email_otp != attrs["otp"]:
            raise serializers.ValidationError({"otp": "Invalid OTP."})

        attrs["user"] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data["user"]
        user.is_verified = True
        user.email_otp = None
        user.otp_created_at = None
        user.save(update_fields=["is_verified", "email_otp", "otp_created_at", "updated_at"])
        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate_email(self, value):
        return value.lower().strip()

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")
        user = authenticate(username=email, password=password)

        if not user:
            raise serializers.ValidationError({"detail": "Invalid email or password."})
        if not user.is_active:
            raise serializers.ValidationError({"detail": "Account is disabled."})
        if not user.is_verified:
            raise serializers.ValidationError({"detail": "Email address is not verified."})

        refresh = RefreshToken.for_user(user)

        attrs["user"] = user
        attrs["refresh"] = str(refresh)
        attrs["access"] = str(refresh.access_token)
        return attrs


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.lower().strip()

    def validate(self, attrs):
        try:
            user = User.objects.get(email=attrs["email"])
        except User.DoesNotExist as exc:
            raise serializers.ValidationError({"email": "User not found."}) from exc

        attrs["user"] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data["user"]
        otp = generate_otp()
        user.email_otp = otp
        user.otp_created_at = timezone.now()
        user.save(update_fields=["email_otp", "otp_created_at", "updated_at"])
        send_otp_email(user.email, user.full_name, otp, purpose="password reset")
        return user


class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(min_length=6, max_length=6)
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate_email(self, value):
        return value.lower().strip()

    def validate_new_password(self, value):
        validate_password(value)
        return value

    def validate(self, attrs):
        try:
            user = User.objects.get(email=attrs["email"])
        except User.DoesNotExist as exc:
            raise serializers.ValidationError({"email": "User not found."}) from exc

        if not user.email_otp or not user.otp_created_at:
            raise serializers.ValidationError({"otp": "OTP not found. Please request a new one."})

        if is_otp_expired(user.otp_created_at):
            raise serializers.ValidationError({"otp": "OTP has expired. Please request a new one."})

        if user.email_otp != attrs["otp"]:
            raise serializers.ValidationError({"otp": "Invalid OTP."})

        attrs["user"] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data["user"]
        user.set_password(self.validated_data["new_password"])
        user.email_otp = None
        user.otp_created_at = None
        user.save(update_fields=["password", "email_otp", "otp_created_at", "updated_at"])
        return user
