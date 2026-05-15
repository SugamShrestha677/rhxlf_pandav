import json
from channels.generic.websocket import AsyncWebsocketConsumer

class EnrollmentProgressConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.enrollment_id = self.scope['url_route']['kwargs']['enrollment_id']
        self.group_name = f"enrollment_{self.enrollment_id}"

        # Join enrollment group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
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

        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'progress': progress,
            'status': status,
            'score': score
        }))
