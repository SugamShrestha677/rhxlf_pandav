from rest_framework import serializers
from .models import Badge, StudentBadge

class BadgeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Badge
        fields = ['id', 'name', 'description', 'image_url', 'criteria', 'created_at']

class StudentBadgeSerializer(serializers.ModelSerializer):
    badge = BadgeSerializer(read_only=True)
    student_name = serializers.CharField(source='student.get_full_name', read_only=True)

    class Meta:
        model = StudentBadge
        fields = ['id', 'student_name', 'badge', 'issued_at', 'metadata']
