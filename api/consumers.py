# api/consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer


class BannerConsumer(AsyncWebsocketConsumer):
    group_name = "banner_broadcast"

    async def connect(self):
        # 그룹에 참여
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        # 그룹에서 제거
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        # 클라이언트에서 오는 메시지 처리 (지금은 단순 에코 정도만)
        if text_data:
          # 원하면 에코:
          await self.send(text_data=text_data)

    # group_send 로 호출될 핸들러(type 이름과 메서드명이 매핑됨)
    async def banner_message(self, event):
        """
        예:
        channel_layer.group_send(
            "banner_broadcast",
            {"type": "banner_message", "message": {"text": "..."}}
        )
        """
        message = event.get("message", {})
        await self.send(text_data=json.dumps(message))
