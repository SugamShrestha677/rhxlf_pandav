from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import EventViewSet, EventRegistrationViewSet

router = DefaultRouter()
router.register(r'events', EventViewSet, basename='events')
router.register(r'registrations', EventRegistrationViewSet, basename='event-registrations')

urlpatterns = [
    path('', include(router.urls)),
]
