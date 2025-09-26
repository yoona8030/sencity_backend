# api/metrics/signals.py
from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver
from typing import TYPE_CHECKING, Any

# ---- 타입 전용 임포트 (에디터 만족용) ----
if TYPE_CHECKING:
    from api.models import Report as ReportModel
else:
    class ReportModel:  # 에디터용 더미
        pass

# ---- 안전 임포트 (런타임용) ----
try:
    from api.metrics.models import Event
except Exception:
    Event = None  # type: ignore

try:
    from api.models import Report  # 실제 sender로 쓸 객체
except Exception:
    Report = None  # type: ignore

try:
    from api.metrics.services import update_stats_cache  # optional
except Exception:
    update_stats_cache = None  # type: ignore


if Report is not None and Event is not None:
    @receiver(post_save, sender=Report)
    def log_report_create(sender, instance: ReportModel, created: bool, **kwargs: Any):
        """
        Report가 '처음' 생성되면:
          1) report_create 이벤트 기록
          2) (선택) 통계 갱신 시도 or 즉시 stats_reflected 기록
        """
        if not created:
            return

        meta: dict = {
            "report_id": getattr(instance, "id", None),
            "species_id": getattr(instance, "animal_id", None),
        }

        lat = getattr(instance, "lat", None)
        lng = getattr(instance, "lng", None)
        if lat is None or lng is None:
            loc = getattr(instance, "location", None)
            if loc is not None:
                lat = getattr(loc, "lat", None)
                lng = getattr(loc, "lng", None)
        if lat is not None and lng is not None:
            meta["lat"] = lat
            meta["lng"] = lng

        # 1) 신고 생성 이벤트
        try:
            Event.objects.create(
                user=getattr(instance, "user", None),
                event_type="report_create",
                meta=meta,
            )
        except Exception:
            pass

        # 2) 통계 반영 이벤트
        try:
            if callable(update_stats_cache):
                update_stats_cache(report_id=getattr(instance, "id", None), delay_sec=2.0)
            else:
                Event.objects.create(
                    event_type="stats_reflected",
                    meta={"report_id": getattr(instance, "id", None), "source": "signal"},
                )
        except Exception:
            try:
                Event.objects.create(
                    event_type="stats_reflected",
                    meta={"report_id": getattr(instance, "id", None), "source": "signal_error"},
                )
            except Exception:
                pass
