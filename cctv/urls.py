from django.urls import path
from .views import proxy_stream

urlpatterns = [
    path("proxy/<int:camera_id>/", proxy_stream, name="cctv_proxy"),
]
