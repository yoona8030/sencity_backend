# cctv/consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer

class CameraConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.camera_id = self.scope["url_route"]["kwargs"]["camera_id"]
        self.group_name = f"cctv_{self.camera_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # 워커가 group_send({"type": "prediction", "data": {...}})로 보낸 메시지를 전달
    async def prediction(self, event):
        await self.send(text_data=json.dumps(event["data"]))
