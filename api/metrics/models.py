from django.db import models
from django.conf import settings

class Event(models.Model):
    """
    앱/웹에서 올라오는 KPI 이벤트 로그.
    - 필수: event_type
    - 선택: user, device_id, meta
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
    )
    # ✅ 자유형 이벤트명 (예: report_submit_click / success / fail 등)
    event_type = models.CharField(max_length=100)

    created_at = models.DateTimeField(auto_now_add=True)

    # ✅ 기기 식별자는 조금 여유 있게
    device_id = models.CharField(max_length=128, blank=True, default="")

    # ✅ 기본값을 dict로 — null 처리에서 오는 400 방지
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["event_type", "created_at"]),
            models.Index(fields=["user", "created_at"]),
        ]
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:  # pragma: no cover
        uid = self.user_id or "-"
        return f"{self.event_type} / {uid} / {self.created_at:%Y-%m-%d %H:%M:%S}"
