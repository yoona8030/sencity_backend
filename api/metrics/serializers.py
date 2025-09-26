# api/metrics/serializers.py
from __future__ import annotations
from typing import Any, Dict, Optional

from rest_framework import serializers
from .models import Event


def _validate_event_type(value: str) -> str:
    """
    프런트 임의 이벤트명을 허용(예: report_submit_click, map_view 등).
    슬러그 형태만 간단히 검증.
    """
    if not isinstance(value, str):
        raise serializers.ValidationError("event_type must be a string.")
    v = value.strip()
    if not v:
        raise serializers.ValidationError("event_type is required.")
    if len(v) > 64:
        raise serializers.ValidationError("event_type too long (<=64).")
    import re
    if not re.fullmatch(r"[a-z0-9_:-]+", v):
        raise serializers.ValidationError("event_type must match [a-z0-9_:-]+")
    return v


class EventCreateSerializer(serializers.ModelSerializer):
    # 🔁 자유 문자열 허용 (기존 ChoiceField 제거)
    event_type = serializers.CharField(required=True)
    device_id = serializers.CharField(required=False, allow_blank=True, max_length=64)
    meta = serializers.JSONField(required=False, allow_null=True)

    class Meta:
        model = Event
        fields = ("event_type", "device_id", "meta")

    def validate_event_type(self, value: str) -> str:
        return _validate_event_type(value)

    def validate_meta(self, value: Optional[Dict[str, Any]]):
        """
        meta를 dict/JSON으로 강제하고 과도한 크기 차단(로그 폭주 예방).
        """
        if value is None:
            return None
        if not isinstance(value, dict):
            raise serializers.ValidationError("meta must be an object (JSON).")
        if len(str(value)) > 4000:
            raise serializers.ValidationError("meta is too large.")
        return value

    def create(self, validated_data):
        """
        인증된 사용자면 user를 자동 연결.
        """
        request = self.context.get("request")
        user = None
        if request is not None and getattr(request, "user", None) and request.user.is_authenticated:
            user = request.user
        return Event.objects.create(user=user, **validated_data)


class EventReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ("id", "user", "event_type", "created_at", "device_id", "meta")
        read_only_fields = fields
