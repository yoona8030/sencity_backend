# api/ai/views.py
from __future__ import annotations
import base64
from typing import Any, Dict, Optional

from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from django.http import JsonResponse

from .utils import (
    auth_ok, should_fire, record_fire,
    normalize_label, map_to_display_label,
    resolve_device, resolve_coords,
    resolve_animal_fk, resolve_user_for_ai,
    create_report_and_broadcast,
)

# predictor는 있으면 사용, 없으면 스킵
try:
    from .predictor import predictor  # Optional
except Exception:
    predictor = None


@method_decorator(csrf_exempt, name="dispatch")
class PingView(APIView):
    authentication_classes: list = []
    permission_classes: list = []
    def get(self, request):
        return Response({"ok": True, "service": "ai", "env": settings.DEBUG})


@method_decorator(csrf_exempt, name="dispatch")
class HeartbeatView(APIView):
    """
    YOLO/게이트웨이에서 장치 하트비트를 칠 때 사용(선택).
    POST /api/ai/heartbeat/  { "device_id": 1 }
    """
    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request):
        if not auth_ok(request):
            return Response({"detail": "unauthorized"}, status=status.HTTP_401_UNAUTHORIZED)

        device_id = request.data.get("device_id")
        dev = resolve_device(device_id)
        if not dev:
            return Response({"detail": "device not found"}, status=status.HTTP_404_NOT_FOUND)

        # 하트비트 갱신
        try:
            dev.mark_heartbeat()
        except Exception:
            # mark_heartbeat 없으면 무시
            pass

        return Response({"ok": True, "device": dev.id})


@method_decorator(csrf_exempt, name="dispatch")
class DetectionIngestView(APIView):
    """
    YOLO/게이트웨이에서 감지 결과를 전송.
    - 인증: 헤더 X-API-KEY
    - Content-Type:
        1) application/json
            {
              "device_id": 1,
              "label": "wild_boar",        # YOLO가 라벨 제공 시
              "prob": 0.87,                # 0~1
              "lat": 37.55, "lng": 127.08, # 선택
              "image_base64": "<data>"     # 선택 (predictor 사용 시)
            }
        2) multipart/form-data
            - fields: device_id, label(선택), prob(선택), lat(선택), lng(선택)
            - files: image (선택)
    - 응답: {ok, report_id?, animal, prob, event}
    """
    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request):
        if not auth_ok(request):
            return Response({"detail": "unauthorized"}, status=status.HTTP_401_UNAUTHORIZED)

        # ---------- 1) 입력 파싱 ----------
        data: Dict[str, Any] = dict(request.POST or request.data)

        device_id = data.get("device_id") or data.get("camera_id")
        dev = resolve_device(device_id)
        if not dev:
            return Response({"detail": "device not found"}, status=status.HTTP_404_NOT_FOUND)

        # 하트비트 갱신(감지 시 ONLINE 유지)
        try:
            dev.mark_heartbeat()
        except Exception:
            pass

        # 확률 임계치
        try:
            min_prob = float(getattr(settings, "AI_MIN_PROB", 0.5))
        except Exception:
            min_prob = 0.5

        # prob
        prob: Optional[float] = None
        if "prob" in data and data["prob"] is not None:
            try:
                prob = float(data["prob"])
            except Exception:
                pass

        # ---------- 2) 이미지 분류(predictor) or YOLO 라벨 ----------
        img_bytes: Optional[bytes] = None

        # multipart: request.FILES
        if "image" in getattr(request, "FILES", {}):
            img_bytes = request.FILES["image"].read()
        # json base64
        elif "image_base64" in data and data["image_base64"]:
            try:
                img_bytes = base64.b64decode(data["image_base64"])
            except Exception:
                img_bytes = None

        # 우선순위: predictor → 요청에 label 제공
        label_raw: Optional[str] = None
        if predictor is not None and img_bytes:
            try:
                top1 = predictor.predict(img_bytes, topk=1)[0]
                label_raw = str(top1["label"])
                # predictor 확률 사용(요청 prob와 충돌 시 더 높은 값 사용)
                p2 = float(top1["prob"])
                prob = max(prob, p2) if prob is not None else p2
            except Exception:
                pass

        if not label_raw:
            label_raw = (data.get("label") or "").strip()

        if not label_raw and prob is None:
            return Response({"detail": "label or image required"}, status=400)

        # 확률 임계치 확인
        if prob is not None and prob < min_prob:
            # 시각화만 브로드캐스트 하고 신고는 생성 안 함
            display = map_to_display_label(label_raw)
            return Response({"ok": True, "event": "below_threshold", "animal": display, "prob": prob}, status=200)

        # ---------- 3) 중복 억제 (쿨다운) ----------
        label_key = normalize_label(label_raw)
        if not should_fire(dev.id, label_key):
            display = map_to_display_label(label_raw)
            return Response({"ok": True, "event": "cooldown", "animal": display, "prob": prob}, status=200)

        record_fire(dev.id, label_key)

        # ---------- 4) 좌표/주소/동물 FK/유저 해석 ----------
        lat, lng = resolve_coords(data, dev)
        animal_fk, animal_name = resolve_animal_fk(label_key)
        user = resolve_user_for_ai()

        display_label = animal_fk.name if animal_fk else map_to_display_label(label_key)
        report_region = data.get("report_region") or f"{dev.name} 주변"

        # ---------- 5) 신고 생성 + WS 브로드캐스트 ----------
        created, rid = create_report_and_broadcast(
            device=dev,
            animal_fk=animal_fk,
            animal_name=animal_name,
            prob=prob,
            lat=lat,
            lng=lng,
            user=user,
            report_region=report_region,
            source="cctv",
            status_value="checking",
            title=f"{display_label} 감지",
        )

        return Response({
            "ok": True,
            "event": "report_created" if created else "visual_only",
            "report_id": rid,
            "animal": display_label,
            "prob": prob,
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

# --- YOLO control stubs -------------------------------------------------
@csrf_exempt
@api_view(["POST"])
@authentication_classes([])   # 인증 미적용(향후 토큰 적용 예정)
@permission_classes([])
def yolo_start(request):
    """
    TODO: 여기에 YOLO 프로세스 시작 로직(서브프로세스/서비스 호출 등) 연결
    """
    return JsonResponse({"ok": True, "action": "start", "message": "YOLO start (stub)"})


@csrf_exempt
@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def yolo_stop(request):
    """
    TODO: 여기에 YOLO 프로세스 중지 로직 연결
    """
    return JsonResponse({"ok": True, "action": "stop", "message": "YOLO stop (stub)"})


@csrf_exempt
@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def yolo_status(request):
    """
    TODO: 여기서 실제 상태값을 반환하도록 구현 (예: running/idle/error)
    """
    return JsonResponse({"ok": True, "status": "idle", "message": "YOLO status (stub)"})
