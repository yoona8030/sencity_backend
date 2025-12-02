# sencity_backend/asgi.py
import os
import django

from django.core.asgi import get_asgi_application
from django.urls import path

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

from sencity_backend.firebase_init import *  # 기존 Firebase 초기화 유지
from api.consumers import BannerConsumer


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sencity_backend.settings")
django.setup()

# HTTP용 기본 ASGI 앱
django_asgi_app = get_asgi_application()

# WebSocket URL 패턴
websocket_urlpatterns = [
    path("ws/banner/", BannerConsumer.as_asgi()),
]

# 최종 ASGI application
application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(
            URLRouter(websocket_urlpatterns),
        ),
    }
)
