from django.urls import path
from .views import (
    PingView,
    HeartbeatView,
    DetectionIngestView,
    yolo_start,
    yolo_stop,
    yolo_status,
)

app_name = "ai"

urlpatterns = [
    path("ping/", PingView.as_view(), name="ai-ping"),
    path("yolo/start/", yolo_start, name="yolo_start"),
    path("yolo/stop/", yolo_stop, name="yolo_stop"),
    path("yolo/status/", yolo_status, name="yolo_status"),
    path("detections/", DetectionIngestView.as_view(), name="ai-detection"),
    path("heartbeat/", HeartbeatView.as_view(), name="ai-heartbeat"),
]
