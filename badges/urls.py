from django.urls import path
from .views import StudentBadgeListView, CourseBadgeListView, VerifyBadgeView

urlpatterns = [
    path('student/badges/', StudentBadgeListView.as_view(), name='student-badges'),
    path('courses/<int:course_id>/badges/', CourseBadgeListView.as_view(), name='course-badges'),
    path('verify/badge/<int:id>/', VerifyBadgeView.as_view(), name='verify-badge'),
]
