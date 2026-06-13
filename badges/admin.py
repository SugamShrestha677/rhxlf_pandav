from django.contrib import admin
from .models import Badge, StudentBadge

@admin.register(Badge)
class BadgeAdmin(admin.ModelAdmin):
    list_display = ('name', 'course', 'created_at')
    search_fields = ('name', 'course__title')
    list_filter = ('course',)

@admin.register(StudentBadge)
class StudentBadgeAdmin(admin.ModelAdmin):
    list_display = ('student', 'badge', 'issued_at')
    search_fields = ('student__email', 'badge__name')
    list_filter = ('badge', 'issued_at')
