from rest_framework import generics, permissions
from rest_framework.response import Response
from .models import Badge, StudentBadge
from .serializers import BadgeSerializer, StudentBadgeSerializer

class StudentBadgeListView(generics.ListAPIView):
    serializer_class = StudentBadgeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return StudentBadge.objects.filter(student=self.request.user).select_related('badge', 'student')

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            "success": True,
            "message": "Student badges retrieved successfully",
            "data": serializer.data,
            "errors": None,
            "status_code": 200
        })

class CourseBadgeListView(generics.ListAPIView):
    serializer_class = BadgeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        course_id = self.kwargs.get('course_id')
        return Badge.objects.filter(course_id=course_id)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            "success": True,
            "message": "Course badges retrieved successfully",
            "data": serializer.data,
            "errors": None,
            "status_code": 200
        })

class VerifyBadgeView(generics.RetrieveAPIView):
    queryset = StudentBadge.objects.all()
    serializer_class = StudentBadgeSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = 'id'

    def retrieve(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            return Response({
                "success": True,
                "message": "Badge verified successfully",
                "data": serializer.data,
                "errors": None,
                "status_code": 200
            })
        except Exception as e:
            return Response({
                "success": False,
                "message": "Badge not found",
                "data": None,
                "errors": str(e),
                "status_code": 404
            }, status=404)
