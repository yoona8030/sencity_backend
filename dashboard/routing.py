# 파일: dashboard/routing.py
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r"^ws/cctv/(?P<cam_id>\d+)/$", consumers.CCTVConsumer.as_asgi()),
]
