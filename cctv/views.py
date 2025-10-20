# cctv/views.py
from django.http import StreamingHttpResponse, Http404
from django.shortcuts import get_object_or_404
import requests
from .models import Camera

def _iter_mjpeg(url: str):
    # 단순 프록시 (브라우저 ↔ ESP32-CAM 사이)
    with requests.get(url, stream=True, timeout=10) as r:
        r.raise_for_status()
        for chunk in r.iter_content(chunk_size=1024):
            if chunk:
                yield chunk

def proxy_stream(request, camera_id: int):
    cam = get_object_or_404(Camera, pk=camera_id, is_active=True)
    try:
        return StreamingHttpResponse(
            _iter_mjpeg(cam.stream_url),
            content_type="multipart/x-mixed-replace; boundary=--frame"
        )
    except Exception as e:
        raise Http404(str(e))
