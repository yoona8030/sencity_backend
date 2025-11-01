# api/ai/utils.py
from __future__ import annotations
import time
from typing import Any, Dict, Optional, Tuple

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from django.conf import settings
from django.contrib.auth import get_user_model
from django.apps import apps  # <- 핵심

# ============================================================
# 0) 모델 안전 로드 (앱 라벨 기준)
# ============================================================

def _get_model(app_label: str, model_name: str):
    try:
        return apps.get_model(app_label, model_name)
    except Exception:
        return None

# 프로젝트 구조에 맞춰 우선순위로 해석
CCTVDevice = _get_model("dashboard", "CCTVDevice") or _get_model("api.dashboard", "CCTVDevice")
Report = (
    _get_model("reports", "Report")
    or _get_model("api.reports", "Report")
    or _get_model("dashboard", "Report")        # ✅ 추가
    or _get_model("api.dashboard", "Report")    # ✅ 추가
)
# Animal 은 위치가 다양할 수 있어 후보를 순차 조회
Animal = (
    _get_model("animals", "Animal") or
    _get_model("dashboard", "Animal") or
    _get_model("api.animals", "Animal") or
    _get_model("api.dashboard", "Animal")
)

# ============================================================
# 1) 인증
# ============================================================

def auth_ok(request) -> bool:
    api_key = request.headers.get("X-API-KEY")
    return bool(api_key) and api_key == getattr(settings, "AI_INGEST_TOKEN", "")

# ============================================================
# 2) 디바이스/좌표 해석
# ============================================================

def resolve_device(device_id: Any):
    if CCTVDevice is None or device_id is None:
        return None
    try:
        return CCTVDevice.objects.get(id=int(device_id))
    except Exception:
        return None

def resolve_coords(data: Dict[str, Any], dev) -> Tuple[Optional[float], Optional[float]]:
    lat = data.get("lat")
    lng = data.get("lng")
    try:
        lat = float(lat) if lat is not None else None
    except Exception:
        lat = None
    try:
        lng = float(lng) if lng is not None else None
    except Exception:
        lng = None
    if (lat is None or lng is None) and dev is not None:
        lat = lat if lat is not None else getattr(dev, "lat", None)
        lng = lng if lng is not None else getattr(dev, "lng", None)
    return lat, lng

# ============================================================
# 3) 라벨 정규화/매핑
# ============================================================

_LABEL_MAP = {
    "wild_boar": "멧돼지",
    "boar": "멧돼지",
    "raccoon": "너구리",
    "roe_deer": "고라니",
    "deer": "고라니",
    "cat": "고양이",
    "dog": "개",
}

def normalize_label(label: str) -> str:
    return (label or "").strip().lower().replace(" ", "_")

def map_to_display_label(label: str) -> str:
    key = normalize_label(label)
    return _LABEL_MAP.get(key, label or "미상")

def resolve_animal_fk(label_key: str):
    """
    Animal FK가 있으면 FK를, 없으면 문자열 라벨을 반환
    """
    display = _LABEL_MAP.get(label_key, None)
    name_for_fk = display if display else label_key
    if Animal is None:
        return None, (display or label_key or "미상")
    try:
        obj = Animal.objects.filter(name__iexact=name_for_fk).first()
        if obj:
            return obj, None
    except Exception:
        pass
    return None, (display or label_key or "미상")

# ============================================================
# 4) 시스템 유저
# ============================================================

def resolve_user_for_ai():
    User = get_user_model()
    username = getattr(settings, "AI_SYSTEM_USERNAME", "ai_bot")
    try:
        u = User.objects.filter(username=username).first()
        if u:
            return u
        # 없으면 최소권한 계정 생성
        return User.objects.create_user(username=username, password=None, is_staff=True)
    except Exception:
        u = User.objects.filter(is_staff=True).first() or User.objects.filter(is_superuser=True).first()
        if not u:
            raise RuntimeError("AI용 사용자 계정을 찾을 수 없습니다. AI_SYSTEM_USERNAME을 설정하세요.")
        return u

# ============================================================
# 5) 쿨다운 (중복 억제)
# ============================================================

_COOLDOWN_SEC = 10
_LAST_FIRE: Dict[tuple, float] = {}  # (device_id, label_key) -> ts

def should_fire(device_id: int, label_key: str) -> bool:
    ts = _LAST_FIRE.get((device_id, label_key))
    now = time.time()
    return (ts is None) or (now - ts >= _COOLDOWN_SEC)

def record_fire(device_id: int, label_key: str):
    _LAST_FIRE[(device_id, label_key)] = time.time()

# ============================================================
# 6) WS 브로드캐스트 + 신고 생성
# ============================================================

def _broadcast(device_id: int, label: str, prob: float | None, report_id: int | None, event: str):
    try:
        payload = {
            "type": "cctv.event",
            "event": event,  # "report_created" | "visual_only" | ...
            "cameraId": device_id,
            "label": map_to_display_label(label),
            "prob": prob,
            "reportId": report_id,
        }
        layer = get_channel_layer()
        async_to_sync(layer.group_send)(f"cctv_{device_id}", payload)
    except Exception:
        pass

def create_report_and_broadcast(
    *,
    device,
    animal_fk,
    animal_name: Optional[str],
    prob: Optional[float],
    lat: Optional[float],
    lng: Optional[float],
    user,
    report_region: str,
    source: str = "cctv",
    status_value: str = "checking",
    title: Optional[str] = None,
) -> tuple[bool, Optional[int]]:
    if Report is None:
        _broadcast(device.id, animal_name or "미상", prob, None, "visual_only")
        return False, None

    from django.utils import timezone

    candidate = dict(
        title=title or (animal_fk.name if animal_fk else (animal_name or "미상")),
        animal=animal_fk if animal_fk else None,
        animal_name=animal_name if not animal_fk else "",
        report_date=timezone.now(),
        status=status_value,
        report_region=report_region,
        user=user,
        latitude=lat if lat is not None else 0.0,
        longitude=lng if lng is not None else 0.0,
        source="cctv",     # 모델에 없으면 자동 제외
        device=device,     # 모델에 없으면 자동 제외
        prob=prob,         # 모델에 없으면 자동 제외
    )

    model_fields = {f.name for f in Report._meta.get_fields()}
    kwargs = {k: v for k, v in candidate.items() if k in model_fields}

    rpt = Report.objects.create(**kwargs)
    _broadcast(device.id, animal_fk.name if animal_fk else (animal_name or "미상"), prob, rpt.id, "report_created")
    return True, rpt.id
