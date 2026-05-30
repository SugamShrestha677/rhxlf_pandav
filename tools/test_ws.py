import asyncio
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from asgiref.sync import sync_to_async
from courses.routing import websocket_urlpatterns
from courses.views import CourseEnrollmentViewSet

async def run():
    app = URLRouter(websocket_urlpatterns)
    communicator = WebsocketCommunicator(app, '/ws/enrollment/3/progress/')
    connected, _ = await communicator.connect()
    print('CONNECTED:', connected)
    try:
        await sync_to_async(CourseEnrollmentViewSet.broadcast_progress)(3)
        message = await communicator.receive_from(timeout=5)
        print('RECEIVED:', message)
    except Exception as e:
        print('ERROR:', e)
    finally:
        await communicator.disconnect()
        await communicator.wait()

if __name__ == '__main__':
    asyncio.run(run())
