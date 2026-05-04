from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_nested import routers
from .views import (
    CategoryViewSet, CourseViewSet, CourseModuleViewSet, ModuleContentViewSet,
    AssessmentViewSet, CourseEnrollmentViewSet, StudentAssessmentViewSet,
    CertificateViewSet, CourseReviewViewSet, CourseAnnouncementViewSet,
    StudentCoursesAPIView, StudentCourseDetailAPIView,
    StudentEnrolledCoursesAPIView, StudentCourseEnrollAPIView,
    StudentDashboardAPIView
)

router = DefaultRouter()
router.register(r'categories', CategoryViewSet, basename='categories')
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
    path('student/courses/', StudentCoursesAPIView.as_view(), name='student-courses'),
    path('student/courses/enrolled/', StudentEnrolledCoursesAPIView.as_view(), name='student-courses-enrolled'),
    path('student/courses/<int:course_id>/', StudentCourseDetailAPIView.as_view(), name='student-course-detail'),
    path('student/courses/<int:course_id>/enroll/', StudentCourseEnrollAPIView.as_view(), name='student-course-enroll'),
    path('student/dashboard/', StudentDashboardAPIView.as_view(), name='student-dashboard'),
]