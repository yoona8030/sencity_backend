# cctv/consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer

class CameraConsumer(AsyncWebsocketConsumer):
  async def connect(self):
    self.camera_id = self.scope["url_route"]["kwargs"]["camera_id"]
    self.group_name = f"cctv_{self.camera_id}"
    await self.channel_layer.group_add(self.group_name, self.channel_name)
    await self.accept()

  async def disconnect(self, close_code):
    await self.channel_layer.group_discard(self.group_name, self.channel_name)

  # utils._broadcast()가 보내는 type: "cctv.event" 수신 핸들러
  async def cctv_event(self, event):
    await self.send(text_data=json.dumps({
        "event": event.get("event"),
        "cameraId": event.get("cameraId"),
        "label": event.get("label"),
        "prob": event.get("prob"),
        "reportId": event.get("reportId"),
    }))
