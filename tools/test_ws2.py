import asyncio
from channels.testing import WebsocketCommunicator
from courses.consumers import EnrollmentProgressConsumer
from channels.layers import get_channel_layer

async def run():
    communicator = WebsocketCommunicator(EnrollmentProgressConsumer.as_asgi(), "/ws/enrollment/3/progress/")
    connected, _ = await communicator.connect()
    if not connected:
        print('CONNECT FAILED')
        return

    # Send a group message and await consumer receipt
    channel_layer = get_channel_layer()
    await channel_layer.group_send('enrollment_3', {
        'type': 'enrollment_progress_update',
        'progress': 73.5,
        'status': 'active',
        'score': 12,
    })

    try:
        msg = await communicator.receive_json_from(timeout=5)
        print('RECEIVED:', msg)
    except Exception as e:
        print('RECEIVE FAILED:', e)

    await communicator.disconnect()

if __name__ == '__main__':
    asyncio.run(run())
