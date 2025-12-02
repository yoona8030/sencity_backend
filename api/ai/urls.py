# api/ai/urls.py
from django.urls import path

from .views import PingView, ImageClassifyView, YoloClassifyView

app_name = "ai"

urlpatterns = [
    path("ping/", PingView.as_view(), name="ai-ping"),
    path("classify/", ImageClassifyView.as_view(), name="ai-classify"),
    path("classify-yolo/", YoloClassifyView.as_view(), name="classify_yolo"),
]
