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

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.debug(
            'WebSocket connected enrollment=%s group=%s channel=%s',
            self.enrollment_id,
            self.group_name,
            self.channel_name,
        )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.debug(
            'WebSocket disconnected enrollment=%s code=%s',
            self.enrollment_id,
            close_code,
        )

    async def enrollment_progress_update(self, event):
        progress = event['progress']
        status = event['status']
        score = event['score']

        logger.debug(
            'WebSocket sending progress enrollment=%s progress=%s status=%s',
            self.enrollment_id,
            progress,
            status,
        )
        await self.send(text_data=json.dumps({
            'progress': progress,
            'status': status,
            'score': score,
        }))


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get('user')

        if not getattr(user, 'is_authenticated', False):
            await self.close(code=4401)
            return

        self.user_id = user.id
        self.group_name = f"user_{self.user_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.debug(
            'Notification WebSocket connected user=%s group=%s',
            self.user_id,
            self.group_name,
        )

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.debug('Notification WebSocket disconnected user=%s code=%s', getattr(self, 'user_id', None), close_code)

    async def notification_message(self, event):
        notification_data = event['notification']
        logger.debug(
            'WebSocket sending notification user=%s id=%s',
            self.user_id,
            notification_data.get('id'),
        )
        await self.send(text_data=json.dumps(notification_data))
