# api/metrics/services.py
from __future__ import annotations

import threading
from typing import Optional

from django.utils import timezone

try:
    from api.metrics.models import Event
except Exception:
    Event = None  # type: ignore


def _write_stats_reflected(report_id: Optional[int], source: str):
    if Event is None:
        return
    meta = {"source": source}
    if report_id is not None:
        meta["report_id"] = report_id
    # 🔁 문자열 상수 사용 ("stats_reflected")
    try:
        Event.objects.create(event_type="stats_reflected", meta=meta)
    except Exception:
        # 로깅 실패는 서비스에 영향 주지 않음
        pass


def update_stats_cache(report_id: Optional[int] = None, delay_sec: float = 0.0):
    """
    (간단 버전) 통계 캐시를 갱신했다고 가정하고 'stats_reflected' 이벤트만 기록.
    실제 캐시/집계 로직을 붙이려면 여기서 처리한 뒤 이벤트를 쓰면 됨.
    """
    def _job():
        # 실제 집계/캐시 갱신이 있다면 여기서 수행
        _write_stats_reflected(report_id=report_id, source="service")

    if delay_sec and delay_sec > 0:
        t = threading.Timer(delay_sec, _job)
        t.daemon = True
        t.start()
    else:
        _job()
