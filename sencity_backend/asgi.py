# sencity_backend/asgi.py
import os, logging
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from django.urls import path
from cctv.consumers import CameraConsumer

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sencity_backend.settings")

try:
    from .firebase_init import init_firebase
    init_firebase()
except Exception as e:
    logging.getLogger(__name__).warning(f"ASGI에서 Firebase 초기화 실패: {e}")

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter([ path("ws/cctv/<int:camera_id>/", CameraConsumer.as_asgi()) ])
    ),
})
