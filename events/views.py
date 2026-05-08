from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import Event, EventRegistration
from .serializers import EventSerializer, EventCreateUpdateSerializer, EventRegistrationSerializer
from LMS.api import api_error, api_success


class EventViewSet(viewsets.ModelViewSet):
    """ViewSet for Events and Webinars"""
    queryset = Event.objects.all()
    
    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return EventCreateUpdateSerializer
        return EventSerializer
    
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            # Only admin or staff can modify events
            return [permissions.IsAuthenticated()] # Logic handled by role check
        return [permissions.AllowAny()]

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return api_success(data=serializer.data)

    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated and user.role in ['admin', 'staff']:
            return Event.objects.all()
        
        from django.db.models import Q
        if user.is_authenticated:
            # For students/authenticated users, show:
            # 1. Scheduled or Ongoing events
            # 2. Completed events that they are registered for
            return Event.objects.filter(
                Q(status__in=['scheduled', 'ongoing']) | 
                Q(status='completed', registrations__user=user)
            ).distinct()
            
        return Event.objects.filter(status='scheduled')

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def register(self, request, pk=None):
        """Register current user for an event"""
        event = self.get_object()
        user = request.user
        
        if event.status != 'scheduled':
            return api_error(message='Event is not open for registration', status_code=status.HTTP_400_BAD_REQUEST)
        
        if EventRegistration.objects.filter(event=event, user=user).exists():
            return api_error(message='Already registered for this event', status_code=status.HTTP_400_BAD_REQUEST)
        
        if event.current_attendees >= event.max_attendees:
            return api_error(message='Event is full', status_code=status.HTTP_400_BAD_REQUEST)
        
        EventRegistration.objects.create(event=event, user=user)
        
        # Update count
        event.current_attendees = event.registrations.count()
        event.save()
        
        return api_success(message='Successfully registered for event')

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def unregister(self, request, pk=None):
        """Unregister current user from an event"""
        event = self.get_object()
        user = request.user
        
        if event.get_actual_status() == 'completed':
            return api_error(message='Cannot unregister from a completed event', status_code=status.HTTP_400_BAD_REQUEST)
            
        registration = EventRegistration.objects.filter(event=event, user=user).first()
        if not registration:
            return api_error(message='Not registered for this event', status_code=status.HTTP_400_BAD_REQUEST)
        
        registration.delete()
        
        # Update count
        event.current_attendees = event.registrations.count()
        event.save()
        
        return api_success(message='Successfully unregistered from event')


    def perform_create(self, serializer):
        serializer.save(organizer=self.request.user)

    def perform_update(self, serializer):
        if self.request.user.role not in ['admin', 'staff']:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only admin or staff can modify events")
        
        instance = self.get_object()
        if instance.get_actual_status() == 'completed':
            return api_error(message='Cannot edit a completed event', status_code=status.HTTP_400_BAD_REQUEST)
        
        serializer.save()

    def perform_destroy(self, instance):
        if self.request.user.role not in ['admin', 'staff']:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only admin or staff can delete events")
        
        if instance.get_actual_status() == 'completed':
            return api_error(message='Cannot delete a completed event', status_code=status.HTTP_400_BAD_REQUEST)
            
        instance.delete()

class EventRegistrationViewSet(viewsets.ModelViewSet):
    """ViewSet for Event Registrations (Admin/Staff only)"""
    queryset = EventRegistration.objects.all()
    serializer_class = EventRegistrationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_update(self, serializer):
        if self.request.user.role not in ['admin', 'staff']:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only admin or staff can modify registrations")
        
        instance = self.get_object()
        if instance.event.get_actual_status() == 'completed':
            from rest_framework.exceptions import ValidationError
            raise ValidationError("Cannot modify registration for a completed event")
        
        serializer.save()

    def perform_destroy(self, instance):
        if self.request.user.role not in ['admin', 'staff']:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only admin or staff can delete registrations")
        
        if instance.event.get_actual_status() == 'completed':
            from rest_framework.exceptions import ValidationError
            raise ValidationError("Cannot remove attendee from a completed event")
            
        instance.delete()
        
        # Update attendee count
        event = instance.event
        event.current_attendees = event.registrations.count()
        event.save()

    def get_queryset(self):
        user = self.request.user
        if user.role in ['admin', 'staff']:
            return EventRegistration.objects.all()
        return EventRegistration.objects.filter(user=user)
