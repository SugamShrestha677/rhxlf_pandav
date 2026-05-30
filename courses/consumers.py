import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .models import CourseEnrollment


logger = logging.getLogger(__name__)


def _user_can_access_enrollment(enrollment_id, user_id):
    return CourseEnrollment.objects.filter(pk=enrollment_id, student_id=user_id).exists()


user_can_access_enrollment = database_sync_to_async(_user_can_access_enrollment)

class EnrollmentProgressConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.enrollment_id = self.scope['url_route']['kwargs']['enrollment_id']
        self.group_name = f"enrollment_{self.enrollment_id}"

        user = self.scope.get('user')
        if not getattr(user, 'is_authenticated', False):
            await self.close(code=4401)
            return

        if not await user_can_access_enrollment(self.enrollment_id, user.id):
            await self.close(code=4403)
            return

        # Join enrollment group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )

        logger.debug(
            "WebSocket connect - enrollment=%s channel=%s group=%s",
            self.enrollment_id,
            self.channel_name,
            self.group_name,
        )
        await self.accept()

    async def disconnect(self, close_code):
        # Leave enrollment group
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    # Receive message from room group
    async def enrollment_progress_update(self, event):
        progress = event['progress']
        status = event['status']
        score = event['score']

        logger.debug(
            "WebSocket sending to client (enrollment=%s): %s",
            self.enrollment_id,
            event,
        )
        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'progress': progress,
            'status': status,
            'score': score
        }))
