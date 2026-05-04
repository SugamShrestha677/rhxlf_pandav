from django.db import models
from django.conf import settings
from django.utils import timezone


class Event(models.Model):
    """Events and webinars model"""
    
    EVENT_TYPE_CHOICES = [
        ('webinar', 'Webinar'),
        ('workshop', 'Workshop'),
        ('seminar', 'Seminar'),
        ('networking', 'Networking'),
        ('other', 'Other'),
    ]
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('ongoing', 'Ongoing'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    description = models.TextField()
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES, default='webinar')
    
    # Timing
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    
    # Location/Platform
    is_online = models.BooleanField(default=True)
    location = models.CharField(max_length=255, blank=True, null=True, help_text="Physical location or Platform name (e.g. Zoom)")
    meeting_link = models.URLField(max_length=500, blank=True, null=True)
    
    # Media
    banner_url = models.URLField(max_length=500, blank=True, null=True)
    
    # Capacity & Registration
    max_attendees = models.IntegerField(default=100)
    current_attendees = models.IntegerField(default=0)
    is_free = models.BooleanField(default=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Creator/Speaker
    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='organized_events'
    )
    speaker_name = models.CharField(max_length=255, blank=True, null=True)
    speaker_bio = models.TextField(blank=True, null=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'events'
        verbose_name = 'Event'
        verbose_name_plural = 'Events'
        ordering = ['start_time']
        indexes = [
            models.Index(fields=['status', 'start_time']),
            models.Index(fields=['event_type']),
        ]
    
    def __str__(self):
        return f"{self.title} ({self.start_time.strftime('%Y-%m-%d %H:%M')})"


class EventRegistration(models.Model):
    """User registrations for events"""
    
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='registrations'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='event_registrations'
    )
    registered_at = models.DateTimeField(auto_now_add=True)
    attended = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'event_registrations'
        unique_together = ['event', 'user']
        verbose_name = 'Event Registration'
        verbose_name_plural = 'Event Registrations'
    
    def __str__(self):
        return f"{self.user.email} registered for {self.event.title}"
