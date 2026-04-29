from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User
from .serializers import (
	ForgotPasswordSerializer,
	LoginSerializer,
	RegisterSerializer,
	ResetPasswordSerializer,
	UserSerializer,
	VerifyEmailSerializer,
)
from .utils import generate_otp, send_otp_email


class RegisterView(APIView):
	permission_classes = [permissions.AllowAny]

	def post(self, request):
		serializer = RegisterSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)
		user = serializer.save()
		return Response(
			{
				"message": "Registration successful. Please verify your email with the OTP sent to your inbox.",
				"user": UserSerializer(user).data,
			},
			status=status.HTTP_201_CREATED,
		)


class VerifyEmailView(APIView):
	permission_classes = [permissions.AllowAny]

	def post(self, request):
		serializer = VerifyEmailSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)
		user = serializer.save()
		return Response(
			{
				"message": "Email verified successfully.",
				"user": UserSerializer(user).data,
			},
			status=status.HTTP_200_OK,
		)


class LoginView(APIView):
	permission_classes = [permissions.AllowAny]

	def post(self, request):
		serializer = LoginSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)
		return Response(
			{
				"message": "Login successful.",
				"access": serializer.validated_data["access"],
				"refresh": serializer.validated_data["refresh"],
				"user": UserSerializer(serializer.validated_data["user"]).data,
			},
			status=status.HTTP_200_OK,
		)


class ResendOTPView(APIView):
	permission_classes = [permissions.AllowAny]

	def post(self, request):
		email = (request.data.get("email") or "").strip().lower()
		if not email:
			return Response({"email": "This field is required."}, status=status.HTTP_400_BAD_REQUEST)

		try:
			user = User.objects.get(email=email)
		except User.DoesNotExist:
			return Response({"email": "User not found."}, status=status.HTTP_404_NOT_FOUND)

		if user.is_verified:
			return Response({"detail": "Email is already verified."}, status=status.HTTP_400_BAD_REQUEST)

		otp = generate_otp()
		user.email_otp = otp
		user.otp_created_at = timezone.now()
		user.save(update_fields=["email_otp", "otp_created_at", "updated_at"])
		send_otp_email(user.email, user.full_name, otp, purpose="email verification")
		return Response(
			{"message": "A new OTP has been sent to your email."},
			status=status.HTTP_200_OK,
		)


class LogoutView(APIView):
	permission_classes = [permissions.AllowAny]

	def post(self, request):
		refresh_token = request.data.get("refresh")
		if not refresh_token:
			return Response({"refresh": "This field is required."}, status=status.HTTP_400_BAD_REQUEST)

		try:
			token = RefreshToken(refresh_token)
			token.blacklist()
		except TokenError:
			return Response({"detail": "Invalid or expired refresh token."}, status=status.HTTP_401_UNAUTHORIZED)

		return Response({"message": "Logout successful."}, status=status.HTTP_200_OK)


class ForgotPasswordView(APIView):
	permission_classes = [permissions.AllowAny]

	def post(self, request):
		serializer = ForgotPasswordSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)
		serializer.save()
		return Response(
			{"message": "Password reset OTP has been sent to your email."},
			status=status.HTTP_200_OK,
		)


class ResetPasswordView(APIView):
	permission_classes = [permissions.AllowAny]

	def post(self, request):
		serializer = ResetPasswordSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)
		serializer.save()
		return Response(
			{"message": "Password reset successful."},
			status=status.HTTP_200_OK,
		)


class MeView(APIView):
	permission_classes = [permissions.IsAuthenticated]

	def get(self, request):
		return Response(UserSerializer(request.user).data, status=status.HTTP_200_OK)


class RefreshView(APIView):
	permission_classes = [permissions.AllowAny]

	def post(self, request):
		serializer = TokenRefreshSerializer(data=request.data)
		try:
			serializer.is_valid(raise_exception=True)
		except (TokenError, InvalidToken):
			return Response({"detail": "Invalid or expired refresh token."}, status=status.HTTP_401_UNAUTHORIZED)
		return Response(serializer.validated_data, status=status.HTTP_200_OK)
