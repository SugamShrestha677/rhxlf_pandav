from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_nested import routers
from .views import (
    CourseViewSet, CourseModuleViewSet, ModuleContentViewSet,
    AssessmentViewSet, CourseEnrollmentViewSet, StudentAssessmentViewSet,
    CertificateViewSet, CourseReviewViewSet, CourseAnnouncementViewSet
)

router = DefaultRouter()
router.register(r'courses', CourseViewSet, basename='courses')
router.register(r'enrollments', CourseEnrollmentViewSet, basename='enrollments')
router.register(r'student-assessments', StudentAssessmentViewSet, basename='student-assessments')
router.register(r'certificates', CertificateViewSet, basename='certificates')

# Nested routers for course modules and content
courses_router = routers.NestedSimpleRouter(router, r'courses', lookup='course')
courses_router.register(r'modules', CourseModuleViewSet, basename='course-modules')
courses_router.register(r'assessments', AssessmentViewSet, basename='course-assessments')
courses_router.register(r'reviews', CourseReviewViewSet, basename='course-reviews')
courses_router.register(r'announcements', CourseAnnouncementViewSet, basename='course-announcements')

# Nested router for module content
modules_router = routers.NestedSimpleRouter(courses_router, r'modules', lookup='module')
modules_router.register(r'contents', ModuleContentViewSet, basename='module-contents')

urlpatterns = [
    path('', include(router.urls)),
    path('', include(courses_router.urls)),
    path('', include(modules_router.urls)),
]