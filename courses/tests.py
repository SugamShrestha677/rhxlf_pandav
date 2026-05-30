from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test.utils import override_settings
from rest_framework.test import APIRequestFactory
from unittest.mock import patch

from .consumers import _user_can_access_enrollment
from .models import Course, CourseEnrollment
from .views import ScormPostbackView


User = get_user_model()


class EnrollmentAccessTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email='owner@example.com',
            password='test-password',
            role='student',
        )
        self.other_student = User.objects.create_user(
            email='other@example.com',
            password='test-password',
            role='student',
        )
        instructor = User.objects.create_user(
            email='instructor@example.com',
            password='test-password',
            role='tutor',
        )
        self.course = Course.objects.create(
            title='WebSocket Access Course',
            slug='websocket-access-course',
            description='Course used to verify enrollment ownership checks.',
            created_by=instructor,
            instructor=instructor,
        )
        self.enrollment = CourseEnrollment.objects.create(
            student=self.owner,
            course=self.course,
        )

    def test_only_enrollment_owner_can_access_progress_socket(self):
        self.assertTrue(_user_can_access_enrollment(self.enrollment.id, self.owner.id))
        self.assertFalse(_user_can_access_enrollment(self.enrollment.id, self.other_student.id))


class ScormPostbackViewTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.instructor = User.objects.create_user(
            email='scorm-instructor@example.com',
            password='test-password',
            role='tutor',
        )
        self.student = User.objects.create_user(
            email='scorm-student@example.com',
            password='test-password',
            role='student',
        )
        self.course = Course.objects.create(
            title='SCORM Postback Course',
            slug='scorm-postback-course',
            description='Course used to verify SCORM postback protection.',
            created_by=self.instructor,
            instructor=self.instructor,
        )
        self.enrollment = CourseEnrollment.objects.create(
            student=self.student,
            course=self.course,
            scorm_registration_id='reg_123',
        )

    def test_postback_rejects_missing_secret(self):
        request = self.factory.post('/api/courses/scorm/postback/', {'registrationId': 'reg_123'}, format='json')

        response = ScormPostbackView.as_view()(request)

        self.assertEqual(response.status_code, 401)

    @override_settings(SCORM_POSTBACK_SECRET='test-secret')
    @patch('courses.views.CourseEnrollmentViewSet.broadcast_progress')
    @patch('courses.views.get_scorm_registration_progress')
    def test_postback_accepts_valid_secret(self, mock_get_progress, mock_broadcast_progress):
        mock_get_progress.return_value = {
            'completion_amount': 0.75,
            'completion': 'INCOMPLETE',
            'success': 'UNKNOWN',
        }

        request = self.factory.post(
            '/api/courses/scorm/postback/?postback_secret=test-secret',
            {'registrationId': 'reg_123'},
            format='json',
        )

        response = ScormPostbackView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.progress_percentage, 75)
        mock_broadcast_progress.assert_called_once_with(self.enrollment.id)
