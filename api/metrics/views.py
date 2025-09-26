# api/metrics/views.py
from __future__ import annotations
from typing import Any, Dict
from collections import defaultdict
from datetime import datetime, time, timedelta

from django.db import transaction
from django.db.models import Count, DateTimeField
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import cache_page

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Event
# ✅ Option A: alias import
from .serializers import (
    EventCreateSerializer as EventInSerializer,
    EventReadSerializer as EventOutSerializer,
)

# Report 집계 (경로 맞게 조정)
try:
    from api.models import Report  # Report: animal_id, report_date 등
except Exception:
    Report = None  # type: ignore


@method_decorator(csrf_exempt, name="dispatch")
class EventIngestView(APIView):
    """
    프런트에서 보내는 이벤트(visit / map_view / login 등) 수집.
    비로그인 허용(AllowAny). 인증되어 있으면 user 자동 연결.
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []  # 인증 강제 비활성화 (CSRF 도 회피)

    @transaction.atomic
    def post(self, request):
        data = request.data.copy() if request.data is not None else {}
        # meta 누락/빈 문자열 대비
        if "meta" not in data or data.get("meta") in (None, ""):
            data["meta"] = {}

        ser = EventInSerializer(data=data)
        ser.is_valid(raise_exception=True)

        user = request.user if getattr(request, "user", None) and request.user.is_authenticated else None
        ev = Event.objects.create(
            user=user,
            event_type=ser.validated_data["event_type"],          # 문자열 상수 사용
            device_id=ser.validated_data.get("device_id") or "",
            meta=ser.validated_data.get("meta") or {},
        )

        out = EventOutSerializer(ev)
        return Response(out.data, status=status.HTTP_201_CREATED)


class StatsView(APIView):
    """
    요청 시 즉석 계산 예시.
    GET /api/metrics/stats/?from=YYYY-MM-DD&to=YYYY-MM-DD
    - Report는 report_date 기준으로 필터(날짜 필드 가정).
    - 동물 집계는 animal_id 기준.
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []

    def get(self, request):
        now = timezone.localtime()
        to_str = request.query_params.get("to")
        from_str = request.query_params.get("from")

        to_date = parse_date(to_str) if to_str else now.date()
        if to_date is None:
            to_date = now.date()

        default_from = to_date - timedelta(days=30)
        from_date = parse_date(from_str) if from_str else default_from
        if from_date is None:
            from_date = default_from

        if from_date > to_date:
            return Response(
                {"detail": "from must be earlier than to (YYYY-MM-DD)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data: Dict[str, Any] = {
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
        }

        if Report is None:
            data["note"] = "Report model not available."
        else:
            # report_date 유형(날짜/일시)에 따라 안전하게 범위 필터
            field = Report._meta.get_field('report_date')
            if isinstance(field, DateTimeField):
                start_dt = timezone.make_aware(datetime.combine(from_date, time.min), now.tzinfo)
                end_dt = timezone.make_aware(datetime.combine(to_date, time.max), now.tzinfo)
                qs = Report.objects.filter(report_date__gte=start_dt, report_date__lte=end_dt)
            else:
                qs = Report.objects.filter(report_date__gte=from_date, report_date__lte=to_date)

            total_reports = qs.count()
            by_animal = list(
                qs.values("animal_id").annotate(count=Count("id")).order_by("-count")
            )
            data.update({
                "total_reports": total_reports,
                "by_animal": by_animal,
            })

        # 통계 반영 이벤트 기록(요청형 계산이므로 source=on_demand)
        try:
            Event.objects.create(
                event_type="stats_reflected",
                meta={"source": "on_demand"},
            )
        except Exception:
            pass

        return Response(data, status=status.HTTP_200_OK)


@method_decorator(cache_page(60), name="dispatch")  # 60초 캐시
class KPIView(APIView):
    """
    GET /api/metrics/kpi/?from=YYYY-MM-DD&to=YYYY-MM-DD
    - 기간 미지정: 최근 30일
    - 응답: reports 요약 + events 집계(visit/map_view/login/report_create/stats_reflected)
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []

    def get(self, request):
        now = timezone.localtime()

        # ----- 기간 파싱 -----
        to_str = request.query_params.get("to")
        from_str = request.query_params.get("from")

        to_date = parse_date(to_str) if to_str else now.date()
        if to_date is None:
            to_date = now.date()

        default_from = to_date - timedelta(days=30)
        from_date = parse_date(from_str) if from_str else default_from
        if from_date is None:
            from_date = default_from

        if from_date > to_date:
            return Response(
                {"detail": "from must be earlier than to (YYYY-MM-DD)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload: Dict[str, Any] = {
            "ts": now.isoformat(),
            "range": {"from": from_date.isoformat(), "to": to_date.isoformat()},
        }

        # ===== Reports 섹션 =====
        reports = {"total": 0, "today": 0, "unresolved": 0}

        if Report is not None:
            field = Report._meta.get_field('report_date')
            # 공통 기준시각
            now = timezone.localtime()
            start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

            if isinstance(field, DateTimeField):
                # 날짜 범위(total/unresolved): __date로 맞추면 간단하고 안전
                rqs = Report.objects.filter(
                    report_date__date__gte=from_date,
                    report_date__date__lte=to_date,
                )
                reports["total"] = rqs.count()

                # 오늘
                reports["today"] = Report.objects.filter(
                    report_date__gte=start_today
                ).count()
            else:
                # report_date가 DateField 인 경우
                rqs = Report.objects.filter(
                    report_date__gte=from_date,
                    report_date__lte=to_date,
                )
                reports["total"] = rqs.count()
                reports["today"] = Report.objects.filter(
                    report_date__gte=start_today.date()
                ).count()

            UNRESOLVED = ("처리중", "접수", "미처리", "대기")
            reports["unresolved"] = rqs.filter(status__in=UNRESOLVED).count()

        payload["reports"] = reports

        # ===== Events 섹션 =====
        eqs = Event.objects.filter(
            created_at__date__gte=from_date,
            created_at__date__lte=to_date,
        ).values("event_type").annotate(c=Count("id"))

        counts = defaultdict(int, {row["event_type"]: row["c"] for row in eqs})

        payload["events"] = {
            "visit":            counts["visit"],
            "map_view":         counts["map_view"],
            "login":            counts["login"],
            "report_create":    counts["report_create"],
            "stats_reflected":  counts["stats_reflected"],
        }

        return Response(payload, status=status.HTTP_200_OK)


class PingView(APIView):
    """헬스체크."""
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []

    def get(self, request):
        return Response({"ok": True, "ts": timezone.now().isoformat()}, status=200)
