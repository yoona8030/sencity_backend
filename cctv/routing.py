# cctv/routing.py
from django.urls import re_path
from .consumers import CameraConsumer

websocket_urlpatterns = [
    re_path(r"^ws/cctv/(?P<camera_id>\d+)/$", CameraConsumer.as_asgi()),
]
