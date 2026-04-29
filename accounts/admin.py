from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .forms import UserChangeForm, UserCreationForm
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
	model = User
	form = UserChangeForm
	add_form = UserCreationForm
	list_display = ("email", "full_name", "role", "is_verified", "is_staff", "is_active")
	list_filter = ("role", "is_verified", "is_staff", "is_active")
	search_fields = ("email", "full_name")
	ordering = ("email",)
	readonly_fields = ("created_at", "updated_at", "otp_created_at")

	fieldsets = (
		(None, {"fields": ("email", "password")}),
		(
			"Personal info",
			{"fields": ("full_name", "role", "is_verified", "email_otp", "otp_created_at")},
		),
		(
			"Permissions",
			{"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
		),
		("Important dates", {"fields": ("last_login", "created_at", "updated_at")}),
	)

	add_fieldsets = (
		(
			None,
			{
				"classes": ("wide",),
				"fields": ("email", "full_name", "role", "password1", "password2", "is_staff", "is_superuser"),
			},
		),
	)
