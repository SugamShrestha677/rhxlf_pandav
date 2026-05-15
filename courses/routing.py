from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/enrollment/(?P<enrollment_id>\w+)/progress/$', consumers.EnrollmentProgressConsumer.as_asgi()),
]
