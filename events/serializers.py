from rest_framework import serializers
from .models import Event, EventRegistration
from django.utils.text import slugify
from django.utils.crypto import get_random_string


class EventSerializer(serializers.ModelSerializer):
    organizer_name = serializers.CharField(source='organizer.email', read_only=True)
    registration_count = serializers.IntegerField(source='registrations.count', read_only=True)
    is_registered = serializers.SerializerMethodField()
    
    class Meta:
        model = Event
        fields = [
            'id', 'title', 'slug', 'description', 'event_type',
            'start_time', 'end_time', 'is_online', 'location',
            'meeting_link', 'banner_url', 'max_attendees',
            'current_attendees', 'is_free', 'price', 'status',
            'organizer', 'organizer_name', 'speaker_name',
            'speaker_bio', 'registration_count', 'is_registered',
            'created_at', 'updated_at', 'actual_status'
        ]
        read_only_fields = ['id', 'slug', 'current_attendees', 'organizer_name', 'registration_count', 'created_at', 'updated_at', 'actual_status']

    actual_status = serializers.SerializerMethodField()

    def get_actual_status(self, obj):
        return obj.get_actual_status()

    def get_is_registered(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return EventRegistration.objects.filter(event=obj, user=request.user).exists()
        return False


class EventCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = [
            'title', 'description', 'event_type', 'start_time',
            'end_time', 'is_online', 'location', 'meeting_link',
            'banner_url', 'max_attendees', 'is_free', 'price',
            'status', 'speaker_name', 'speaker_bio'
        ]

    def create(self, validated_data):
        title = validated_data['title']
        slug = slugify(title)
        original_slug = slug
        counter = 1
        while Event.objects.filter(slug=slug).exists():
            slug = f"{original_slug}-{get_random_string(4)}"
            counter += 1
        
        validated_data['slug'] = slug
        validated_data['organizer'] = self.context['request'].user
        return super().create(validated_data)


class EventRegistrationSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)
    event_title = serializers.CharField(source='event.title', read_only=True)
    
    class Meta:
        model = EventRegistration
        fields = ['id', 'event', 'event_title', 'user', 'user_email', 'registered_at', 'attended']
        read_only_fields = ['id', 'user', 'registered_at']
