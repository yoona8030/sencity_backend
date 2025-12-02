# dashboard/views.py
import cv2, json, re, hashlib, os, typing
import requests, io
import time as pytime
import html as _html
from typing import Tuple, Any
from datetime import datetime, timedelta, time
from functools import wraps
from django.shortcuts import render, redirect
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_GET, require_POST

from django.template.loader import render_to_string
from django.http import JsonResponse, StreamingHttpResponse,  HttpResponse, HttpRequest, HttpResponseBadRequest, HttpResponseRedirect, HttpResponseNotAllowed
from django.conf import settings as dj_settings
from django.contrib.auth.decorators import user_passes_test, login_required
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.contrib.auth.hashers import make_password
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser, Group, User as AuthUser
from django.contrib.sessions.models import Session
from django.contrib import messages
from django.contrib.humanize.templatetags.humanize import naturaltime
from django.core.cache import cache
from django.core.paginator import Paginator, EmptyPage
from django.core.mail import send_mail
from django.db import models
from django.db.models import Count, Q, F, Value, Case, When, CharField, OuterRef, Subquery
from django.db.models.functions import TruncMonth, Coalesce
from django.db.models.fields.files import FieldFile
from django.db.models.fields.related import ForeignObjectRel  # ← 추가
from django.utils import timezone
from django.utils.timesince import timesince
from django.utils.html import strip_tags
from django.utils.http import http_date
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .serializers import DashboardReportListSerializer

from django.apps import apps
from dashboard.models import Animal, CCTVDevice

from api.metrics.services import get_dashboard_summary
from api.constants import UNRESOLVED_STATUSES, RESOLVED_STATUSES
from .models import Content, DashboardSetting

try:
    from .models import LoginLog
    HAS_LOGINLOG = True
except Exception:
    HAS_LOGINLOG = False
    LoginLog = None  # type: ignore

try:
  from api.models import AppBanner
  HAS_APP_BANNER = True
except Exception:
  AppBanner = None
  HAS_APP_BANNER = False

from api.models import Report
try:
    from api.models import Notification
    HAS_NOTIFICATION = True
except Exception:
    Notification = None
    HAS_NOTIFICATION = False

try:
    from api.models import Location
    HAS_LOCATION = True
except Exception:
    HAS_LOCATION = False
try:
    from api.models import Feedback
    HAS_FEEDBACK = True
except Exception:
    Feedback = None
    HAS_FEEDBACK = False

except Exception as e:
    # 로컬 개발 중 임포트 오류를 눈에 띄게 하기 위함
    print("[AI] django_integration import error:", e)
    start_animal_detection = None
    stop_animal_detection = None
    get_detection_status = None

from firebase_admin import messaging

# --- FCM: 만료/삭제 토큰 판별 헬퍼 ------------------------
def _is_unregistered_error(exc) -> bool:
    if not exc:
        return False
    name = (exc.__class__.__name__ or "").lower()
    code = str(getattr(exc, "code", "") or "").lower()
    msg  = str(getattr(exc, "message", "") or str(exc)).lower()
    hay = f"{name} {code} {msg}"

    # FCM/SDK에서 흔히 오는 죽은 토큰 패턴을 넓게 커버
    hints = [
        "unregistered",
        "not registered",
        "registration-token-not-registered",
        "mismatch_sender_id", "mismatch-sender-id", "senderidmismatch",
        "third_party_auth_error", "third-party-auth-error",
        "invalid_registration", "notregistered",
        "requested entity was not found",
    ]
    return any(h in hay for h in hints)

try:
    from api.models import DeviceToken
    HAS_DEVICE_TOKEN = True
except Exception:
    DeviceToken = None
    HAS_DEVICE_TOKEN = False

from .models import CCTVDevice, MotionSensor, Prediction, DashboardSetting
from dashboard.vision.adapter import SingletonClassifier

User = get_user_model()

def is_staff(user):
    return user.is_staff or user.is_superuser
# --- Helper: 카메라/소스 사전 점검(Windows 안정화) ----------------------------
def _precheck_open_webcam(stream_url: Any) -> Tuple[bool, str]:
    """
    stream_url 이 정수(혹은 숫자 문자열)면 Windows에서 DSHOW로 열어보고 isOpened() 확인.
    - 성공: (True, "")
    - 실패: (False, "이유")
    그 외(rtsp/http/파일 경로)는 간단한 유효성만 확인하고 True 반환.
    """
    # OpenCV MSMF 충돌 회피 (전역 보강)
    os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_MSMF", "0")

    # 숫자형 웹캠 인덱스
    if isinstance(stream_url, int) or (isinstance(stream_url, str) and stream_url.isdigit()):
        idx = int(stream_url)
        cap = None
        try:
            cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
            if not cap or not cap.isOpened():
                return False, f"camera index {idx} open failed"
            return True, ""
        except Exception as e:
            return False, f"open exception: {e}"
        finally:
            try:
                if cap:
                    cap.release()
            except Exception:
                pass

    # 네트워크 스트림은 즉시 열어 점검하기 어려우므로 포맷만 확인
    if isinstance(stream_url, str) and (stream_url.startswith("rtsp://") or stream_url.startswith("http://") or stream_url.startswith("https://")):
        return True, ""

    # 파일 경로인 경우 존재 여부만 확인
    if isinstance(stream_url, str):
        if os.path.exists(stream_url):
            return True, ""
        # 숫자도 아니고 URL도 아니고 파일도 아니면 잘못된 입력
        return False, "invalid source"

    # 그 외 타입
    return False, "unsupported source type"


# --- 1) AI 시작 --------------------------------------------------------------
@csrf_exempt
@require_POST
def ai_detection_start(request: HttpRequest):
    """
    POST /dashboard/api/ai/start/
    body: { "stream_url": 0 | "rtsp://..." | "http://.../mjpeg" | "C:\\video.mp4",
            "confidence": 0.25 }
    항상 200으로 응답하며, success 로 성공/실패를 구분합니다.
    """
    if start_animal_detection is None:
        return JsonResponse({"success": False, "error": "integration not available"}, status=200)

    # 요청 본문 파싱
    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        data = {}

    # 파라미터 정리
    stream_url = data.get("stream_url", 0)
    # 숫자 문자열이면 int로 변환
    if isinstance(stream_url, str) and stream_url.isdigit():
        stream_url = int(stream_url)

    try:
        confidence = float(data.get("confidence", 0.5))
    except Exception:
        confidence = 0.5
    confidence = max(0.01, min(0.95, confidence))

    # OpenCV 백엔드 우선순위 (MSMF → DSHOW/FFMPEG)
    os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_MSMF", "0")

    # 카메라/소스 사전 점검
    ok, reason = _precheck_open_webcam(stream_url)
    if not ok:
        return JsonResponse({"success": False, "error": reason}, status=200)

    # 실제 시작
    try:
        ok = start_animal_detection(stream_url, confidence)
        if not ok:
            return JsonResponse({"success": False, "error": "START_FAILED"}, status=200)
    except Exception as e:
        return JsonResponse({"success": False, "error": f"exception: {e}"}, status=200)

    # 짧게 상태 확인(최대 1.2초)
    deadline = pytime.time() + 1.2
    while pytime.time() < deadline:
        try:
            st = get_detection_status() if get_detection_status else {}
            if st.get("is_running"):
                return JsonResponse({"success": True}, status=200)
        except Exception as e:
            return JsonResponse({"success": False, "error": f"status exception: {e}"}, status=200)
        pytime.sleep(0.1)

    # 아직 실행 중이 아니면 AI 내부 사유를 에러로 전달
    st = get_detection_status() if get_detection_status else {}
    return JsonResponse(
        {"success": False, "error": st.get("error") or "NOT_RUNNING"},
        status=200,
    )


# --- 2) AI 상태 --------------------------------------------------------------
@require_http_methods(["GET"])
def ai_detection_status(request: HttpRequest):
    """
    GET /dashboard/api/ai/status/
    """
    if get_detection_status is None:
        return JsonResponse({"success": True, "is_running": False, "detections": [], "frame": None, "total": 0}, status=200)
    try:
        st = get_detection_status()
        # success 키를 항상 포함(프론트 일관성)
        if "success" not in st:
            st = {"success": True, **st}
        return JsonResponse(st, status=200)
    except Exception as e:
        return JsonResponse({"success": False, "is_running": False, "error": f"exception: {e}"}, status=200)


# --- 3) AI 정지 --------------------------------------------------------------
@csrf_exempt
@require_POST
def ai_detection_stop(request: HttpRequest):
    """
    POST /dashboard/api/ai/stop/
    """
    if stop_animal_detection is None:
        return JsonResponse({"success": False, "error": "integration not available"}, status=200)
    try:
        ok = stop_animal_detection()
        return JsonResponse({"success": bool(ok)}, status=200)
    except Exception as e:
        return JsonResponse({"success": False, "error": f"exception: {e}"}, status=200)

def ai_monitor(request):
    """대시보드에서 YOLO 실시간 상태/프레임을 확인하는 간단한 페이지"""
    return render(request, "dashboard/ai_monitor.html")

def _get_model_or_none(app_label: str, model_name: str):
    """apps.get_model 래퍼: 없으면 None."""
    try:
        return apps.get_model(app_label, model_name)
    except Exception:
        return None

def _recent_login_rows_for(user, limit: int = 5):
    """
    LoginLog 모델이 있으면 최근 로그인 5건을, 없으면 빈 리스트를 돌려줍니다.
    필드명(ip, user_agent, created_at)은 존재할 때만 안전 접근.
    """
    LoginLog = _get_model_or_none("dashboard", "LoginLog")
    if not LoginLog:
        return []

    qs = LoginLog.objects.filter(user=user).order_by("-created_at")[:limit]
    rows = []
    for r in qs:
        rows.append({
            "ip": getattr(r, "ip", None),
            "user_agent": getattr(r, "user_agent", None),
            "created_at": (
                timezone.localtime(getattr(r, "created_at")).strftime("%Y-%m-%d %H:%M")
                if getattr(r, "created_at", None) else ""
            ),
        })
    return rows

def _animal_label_or_none(animal):
    """Animal 인스턴스에서 사용 가능한 라벨 필드를 안전하게 반환"""
    if not animal:
        return None
    for f in ("name", "name_kor", "kor_name", "label", "title"):
        val = getattr(animal, f, None)
        if val:
            return str(val)
    return None

# HttpOnly 쿠키 공통 옵션 (개발용; 운영 HTTPS는 secure=True로!)
COOKIE_KW = dict(
    httponly=True,
    samesite='Lax',
    secure=False,
)

def with_admin_jwt_cookies(viewfunc):
    """
    대시보드 페이지(SSR) 응답에 access/refresh 쿠키가 없으면 자동 발급해서 심어준다.
    - 세션으로 이미 로그인한 관리자만 대상(뷰에 @login_required 또는 @user_passes_test(_is_staff)와 함께 사용)
    - API(JSON) 뷰에는 붙이지 말고, '페이지 렌더' 뷰에만 붙이세요.
    """
    @wraps(viewfunc)
    def _wrapped(request, *args, **kwargs):
        resp = viewfunc(request, *args, **kwargs)
        # 페이지 렌더 응답인지(쿠키를 심을 수 있는지)만 간단히 체크
        try:
            has_access = bool(request.COOKIES.get("access"))
            has_refresh = bool(request.COOKIES.get("refresh"))
            if not (has_access and has_refresh) and request.user.is_authenticated:
                rt = RefreshToken.for_user(request.user)
                at = rt.access_token
                resp.set_cookie('access', str(at), **COOKIE_KW)
                resp.set_cookie('refresh', str(rt), **COOKIE_KW)
        except Exception:
            pass
        return resp
    return _wrapped

# ─────────────────────────────────────
# 공통 헬퍼
# ─────────────────────────────────────
def safe_select_related(qs, Model, names: list[str]):
    """names 중 실제로 FK/OneToOne 관계인 것만 select_related에 적용"""
    for n in names:
        if _is_select_related_candidate(Model, n):
            qs = qs.select_related(n)
    return qs

def _notif_user_field(Model) -> str | None:
    """
    Notification 모델에서 '사용자'를 가리키는 필드명을 찾아 반환.
    우선순위: user -> created_by -> sender
    """
    candidates = ["user", "created_by", "sender"]
    for name in candidates:
        if _model_has_field(Model, name):
            return name
    return None

@login_required
@with_admin_jwt_cookies
def home(request):
    # KPI 계산 (오늘은 로컬데이트 기준)
    qs_r = Report.objects.all()
    total = qs_r.count()

    date_field = "report_date" if _model_has_field(Report, "report_date") else (
        "created_at" if _model_has_field(Report, "created_at") else None
    )
    if date_field:
        today_cnt = qs_r.filter(**{f"{date_field}__date": timezone.localdate()}).count()
    else:
        today_cnt = 0

    # ✅ 미해결: checking + on_hold 만 포함
    unresolved = qs_r.filter(status__in=UNRESOLVED_STATUSES).count()

    # ✅ 처리율: 완료/전체 (거절을 처리로 볼지 정책에 따라 RESOLVED_STATUSES에 포함 여부 결정)
    completed = qs_r.filter(status__in=RESOLVED_STATUSES).count()
    rate = int((completed * 100) / total) if total > 0 else 0

    s = _settings_singleton()
    server_banner = (
        s.maintenance_message
        if getattr(s, "show_server_banner", False) and getattr(s, "maintenance_message", "")
        else ""
    )

    # 공지 (HAS_NOTIFICATION일 때만)
    notices = []
    if HAS_NOTIFICATION and Notification is not None:
        qs = Notification.objects.all()
        user_field = _notif_user_field(Notification)
        rels = []
        if user_field:
            rels.append(user_field)
        rels += ["admin", "report"]  # 존재하는 경우만 select_related
        qs = safe_select_related(qs, Notification, rels)
        qs = qs.order_by("-created_at" if _model_has_field(Notification, "created_at") else "-id")[:4]
        notices = [_enrich_notice(n) for n in qs]

    ctx = {
        "notices": notices,
        "stats": {
            "total": total,
            "today": today_cnt,
            "unresolved": unresolved,
            "handled": completed,   # 원래 handled를 쓰신다면 completed로 두는 게 일관됨
            "rate": rate,
        },
        "server_banner": server_banner,
    }
    return render(request, "dashboard/home.html", ctx)

@login_required
@with_admin_jwt_cookies
def reports(request):
    return render(request, 'dashboard/reports.html')

def _is_staff(user):
    return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))

def staff_required_json(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        u = getattr(request, "user", None)
        if not u or not u.is_authenticated or not u.is_staff:
            return JsonResponse({"ok":False, "error":"forbidden"}, status=403)
        return view_func(request, *args, **kwargs)
    return _wrapped

def _settings_singleton() -> DashboardSetting:
    # 기존: get_or_create(id=1) → 기본값 주입 누락 가능
    return DashboardSetting.get_solo()

_SORT_ALLOW = ("-report_date", "report_date")
_SORT_MAP = {
    "newest": "-report_date",
    "desc": "-report_date",
    "-created_at": "-report_date",
    "created_at": "-report_date",
    "oldest": "report_date",
    "asc": "report_date",
}
def norm_sort(v: str) -> str:
    v = (v or "").strip()
    if v in _SORT_ALLOW:
        return v
    return _SORT_MAP.get(v, "-report_date")

def _model_has_field(model, name: str) -> bool:
    return any(getattr(f, "name", None) == name for f in model._meta.get_fields())

# 관계 필드일 때만 select_related 허용
def _is_select_related_candidate(model, name: str) -> bool:
    try:
        f = model._meta.get_field(name)
        # ForeignKey/OneToOne만 True (역참조/Many 등은 False)
        return getattr(f, "is_relation", False) and not isinstance(f, ForeignObjectRel) and (
            getattr(f, "many_to_one", False) or getattr(f, "one_to_one", False)
        )
    except Exception:
        return False

def _latest_feedback_content_subquery():
    """
    Notification.report_id를 기준으로, 가장 최근 Feedback.content를 Subquery로 반환.
    '가장 최근' 판단에 사용할 날짜/정렬 필드를 자동으로 고른다.
    필드 후보: feedback_datetime > created_at > datetime > created > timestamp > id(대체)
    """
    if not HAS_FEEDBACK or Feedback is None:
        return None

    def pick_date_field():
        for name in ("feedback_datetime", "created_at", "datetime", "created", "timestamp"):
            if _model_has_field(Feedback, name):
                return name
        return None

    date_field = pick_date_field()
    order_key = f"-{date_field}" if date_field else "-id"

    # content 필드명이 다르면 여기서 바꿔 주세요. (기본: 'content')
    value_field = "content" if _model_has_field(Feedback, "content") else None
    if not value_field:
        # 안전장치: 텍스트 계열 첫 필드 자동 탐색
        for f in Feedback._meta.get_fields():
            base = getattr(f, "target_field", f)
            if isinstance(base, (models.TextField, models.CharField)):
                value_field = f.name
                break
    if not value_field:
        return None  # 본문 필드를 못 찾으면 주입 생략

    sq = (
        Feedback.objects
        .filter(report=OuterRef("report_id"))
        .order_by(order_key)
        .values(value_field)[:1]
    )
    return Subquery(sq)

# ── AppBanner 필드/로직 헬퍼 ──────────────────────────
def _ab_has_field(name: str) -> bool:
    return HAS_APP_BANNER and any(getattr(f, "name", None) == name for f in AppBanner._meta.get_fields())

def _ab_active_q():
    """
    AppBanner 활성 배너 조건:
    - is_active=True (있을 때)
    - (starts_at <= now) AND (ends_at is null OR ends_at >= now) 기간 충족(필드 있을 때만)
    """
    from django.db.models import Q
    q = Q()
    now = timezone.now()
    # is_active 우선
    if _ab_has_field("is_active"):
        q &= Q(is_active=True)
    # 기간 창
    if _ab_has_field("starts_at"):
        q &= Q(starts_at__lte=now)
    if _ab_has_field("ends_at"):
        q &= (Q(ends_at__isnull=True) | Q(ends_at__gte=now))
    return q

def _ab_set_live(obj, live: bool, *, exclusive: bool = False):
    """
    AppBanner 인스턴스(obj)에 대해 활성/비활성 토글.
    - exclusive=True면 모든 배너를 비활성 후 obj를 활성
    - 필드가 없으면 가능한 범위에서만 처리
    """
    if not HAS_APP_BANNER:
        return

    update_fields = []

    # 독점: 모두 끄기
    if exclusive:
        kw = {}
        if _ab_has_field("is_active"):
            kw["is_active"] = False
        if _ab_has_field("ends_at") and _ab_has_field("starts_at"):
            # 일괄 종료만 하고 싶으면 ends_at=now 로도 가능하지만,
            # is_active가 있으니 is_active=False만으로 충분
            pass
        if kw:
            AppBanner.objects.update(**kw)

    # 대상 상태 설정
    if _ab_has_field("is_active"):
        obj.is_active = bool(live)
        update_fields.append("is_active")

    now = timezone.now()
    if _ab_has_field("starts_at"):
        if live and not getattr(obj, "starts_at", None):
            obj.starts_at = now
            update_fields.append("starts_at")
    if _ab_has_field("ends_at"):
        # 켜질 때는 종료 해제, 꺼질 때는 now로 종료 (정책에 맞게)
        if live:
            if getattr(obj, "ends_at", None) is not None:
                obj.ends_at = None
                update_fields.append("ends_at")
        else:
            obj.ends_at = now
            update_fields.append("ends_at")

    if update_fields:
        obj.save(update_fields=update_fields)
    else:
        obj.save()

# ── Report 필드 유연 처리 ─────────────────────────────

def _date_value(obj):
    for f in ("report_date", "created_at", "submitted_at"):
        if hasattr(obj, f):
            return getattr(obj, f)
    return None

def _region_value(obj):
    for f in ("report_region", "region", "address", "location_name"):
        if hasattr(obj, f):
            v = getattr(obj, f) or ""
            if v:
                return v
    loc = getattr(obj, "location", None)
    if loc:
        for f in ("name", "region", "address", "detail", "road_address"):
            if hasattr(loc, f):
                v = getattr(loc, f) or ""
                if v:
                    return v
    return ""

def _animal_label(obj):
    a = getattr(obj, "animal", None)
    if not a:
        return getattr(obj, "animal_name", "") or ""
    for f in ("name_kor", "name"):
        if hasattr(a, f):
            v = getattr(a, f)
            if v:
                return v
    return ""

def _month_labels_for_year(y: int) -> list[str]:
    return [f"{y}-{m:02d}" for m in range(1, 12 + 1)]

def _animal_model_has(field_name: str) -> bool:
    if not _model_has_field(Report, "animal"):
        return False
    animal_model = Report._meta.get_field("animal").remote_field.model
    return any(getattr(f, "name", None) == field_name for f in animal_model._meta.get_fields())

def _parse_dt(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        dt = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except Exception:
                pass
    if not dt:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt

def _dt_iso(dt):
    if not dt:
        return ""
    try:
        return timezone.localtime(dt).isoformat()
    except Exception:
        return str(dt)

def _latest_feedback_text(rep):
    if not rep or not hasattr(rep, "feedbacks"):
        return None
    try:
        fb = rep.feedbacks.order_by("-id").first()
    except Exception:
        fb = None
    if not fb:
        return None
    for name in ("content", "body", "text", "message", "description"):
        if hasattr(fb, name):
            v = getattr(fb, name)
            if v:
                return str(v)
    for fld in fb._meta.get_fields():
        base = getattr(fld, "target_field", fld)
        if isinstance(base, (models.TextField, models.CharField)):
            v = getattr(fb, fld.name, None)
            if v:
                return str(v)
    return None

def _first_image_field_url(obj, request=None) -> str:
    """
    Report 인스턴스에서 이미지 후보 필드를 순회해 첫 번째 URL을 반환.
    FileField/ ImageField 가 비어 있을 때 .url 접근으로 예외가 나지 않도록
    반드시 f.name 존재 여부로 선행 검사한다.
    """
    CANDIDATES = ("photo", "image", "img", "picture", "photo1", "photo_url")

    for name in CANDIDATES:
        if not hasattr(obj, name):
            continue

        f = getattr(obj, name, None)

        # 1) FileField / ImageField 계열
        if isinstance(f, FieldFile):
            # 파일이 비어 있으면 f.name이 빈 문자열/None 입니다.
            if getattr(f, "name", None):
                try:
                    url = f.url  # name이 있을 때만 안전
                    if url:
                        if request is not None and url.startswith("/"):
                            return request.build_absolute_uri(url)
                        return url
                except Exception:
                    # 스토리지 예외 등은 조용히 패스하고 다음 후보로
                    pass
            continue

        # 2) 문자열 URL이 모델에 저장된 경우 (CharField 등)
        if isinstance(f, str):
            s = f.strip()
            if s:
                # 절대/상대 모두 허용. 상대면 절대 URL로 변환
                if request is not None and s.startswith("/"):
                    return request.build_absolute_uri(s)
                return s

    return ""

def _reporter_name_or_user(r) -> str:
    u = getattr(r, "user", None)
    if u:
        nm = (getattr(u, "get_full_name", lambda: "")() or getattr(u, "username", "") or getattr(u, "email", ""))
        if nm: return nm
    for k in ("reporter_name", "reporter", "contact_name", "writer_name"):
        v = getattr(r, k, None)
        if v: return str(v)
    return "익명"

# ── Notification 표시용 ─────────────────────────────

def _notif_title(n):
    rid = getattr(getattr(n, "report", None), "id", None)
    if getattr(n, "status_change", None):
        base = f"신고 {rid} 상태 변경" if rid else "상태 변경 알림"
        return f"{base}: {n.status_change}"
    if getattr(n, "reply", None):
        return f"신고 {rid} 답글 등록" if rid else "답글 등록 알림"
    t = getattr(n, "type", "") or ""
    return t or "알림"

def _notif_scope(n):
    return "개인" if getattr(n, "user_id", None) else "전체"

def _notif_row(n):
    return {
        "id": n.id,
        "title": _notif_title(n),
        "scope": _notif_scope(n),
        "type": getattr(n, "type", "") or "",
        "created_at": _dt_iso(getattr(n, "created_at", None)) or "",
    }

def _notif_content(n):
    # 서브쿼리로 annotate된 최근 피드백 본문이 있으면 우선 사용
    rt = getattr(n, "reply_text", None)
    if isinstance(rt, str) and rt.strip():
        return _html.unescape(strip_tags(rt)).strip()
    rep = getattr(n, "report", None)
    fb_text = _latest_feedback_text(rep)
    if fb_text:
        s = strip_tags(fb_text)
        s = _html.unescape(s).strip()
        if s:
            return s

    for fname in ("content", "body", "message", "text"):
        v = getattr(n, fname, None)
        if v:
            return str(v)

    r = getattr(n, "reply", None)
    if r:
        if isinstance(r, str):
            s = r.strip()
            if s:
                s = strip_tags(s)
                s = _html.unescape(s)
                return s
        if isinstance(r, dict):
            for k in ("content", "body", "text", "message", "comment", "reply", "description", "html", "message_html"):
                v = r.get(k)
                if v:
                    s = str(v).strip()
                    s = strip_tags(s)
                    s = _html.unescape(s)
                    if s:
                        return s
            rs = _html.unescape(strip_tags(str(r))).strip()
            if rs:
                return rs
        for fname in ("content", "body", "text", "message", "comment", "reply", "description", "html", "message_html"):
            if hasattr(r, fname):
                v = getattr(r, fname, None)
                if v:
                    s = str(v).strip()
                    s = strip_tags(s)
                    s = _html.unescape(s)
                    if s:
                        return s
        s = _html.unescape(strip_tags(str(r))).strip()
        if s and s != "None":
            return s

    sc = getattr(n, "status_change", None)
    if sc:
        try:
            if isinstance(sc, dict):
                f = sc.get("from") or sc.get("old") or "?"
                t = sc.get("to") or sc.get("new") or "?"
                return f"상태가 {f} 에서 {t} 로 변경되었습니다."
            return f"상태 변경: {sc}"
        except Exception:
            return f"상태 변경: {sc}"

    if rep:
        rid = getattr(rep, "id", None)
        title = getattr(rep, "title", "") or ""
        if rid and title:
            return f"신고 {rid} 관련 알림\n제목: {title}"
        if rid:
            return f"신고 {rid} 관련 알림"

    return "내용이 없습니다"


def _user_display_name(u) -> str:
    if not u:
        return "전체"
    nm = ""
    for f in ("get_full_name",):
        if hasattr(u, f):
            try:
                nm = getattr(u, f)() or ""
            except Exception:
                pass
    nm = nm or getattr(u, "first_name", "") or getattr(u, "username", "") or ""
    return nm or f"사용자 #{getattr(u, 'id', '')}".strip()

def _animal_display_name(rep) -> str:
    if not rep:
        return "미상"
    a = getattr(rep, "animal", None)
    if a:
        return getattr(a, "name_kor", None) or getattr(a, "name", None) or "미상"
    for f in ("animal_name", "animal_label"):
        v = getattr(rep, f, None)
        if v:
            return str(v)
    return "미상"

def _title_suggest_from_fields(*, notice_type: str, reply: str, status_change: str, title: str, content: str) -> str:
    """
    프론트의 buildGroupTitle 로직을 거의 그대로 이식한 서버판.
    notice_type 매핑 → 키워드/정규식 탐지 순으로 제목을 제안한다.
    """
    # 1) 고정 매핑 (타입이 오면 최우선 적용)
    type_map = {
        "maintenance": "서비스 점검 안내",
        "release": "업데이트 안내",
        "policy": "정책 변경 안내",
        "event": "이벤트 안내",
        "outage": "서비스 장애 안내",
        "recovery": "서비스 정상화 안내",
        "location_fix": "위치 정보 오류 수정 안내",
        "new_feature": "새로운 기능 추가 안내",
        "weather_alert": "기상 악화 주의 안내",
        "animal_aggression": "동물 공격성 증가 주의",
        "report_surge": "신고 급증 주의",
        "safety_alert": "주의/위험 안내",
        "wildfire_alert": "산불 주의 안내",
        "environment": "환경 보호 안내",
        "cleanup": "환경 정화 활동 안내",
        "litter": "쓰레기/무단 투기 주의",
    }
    key = (notice_type or "").strip().lower()
    if key in type_map:
        return type_map[key]

    # 2) 본문 합치기
    hay = " ".join([
        title or "", reply or "", content or "", status_change or "", notice_type or ""
    ]).lower()

    # 3) 정상화 / 장애
    if re.search(r"(복구|정상화|recovered|recovery|restored|resolved)", hay):
        return "서비스 정상화 안내"
    if re.search(r"(장애|오류|접속\s*불가|에러|error|5\d{2}|outage|downtime|service\s*unavailable)", hay):
        return "서비스 장애 안내"

    # 4) 기상 관련
    weather_hit = re.search(
        r"(태풍|호우|폭우|강풍|폭설|대설|적설|한파|폭염|미세먼지|초미세먼지|황사|우천|우박|비바람|기상\s*특보|bad\s*weather|storm|typhoon|hail|hailstorm|heavy\s*(rain|snow)|snow\s*accumulation|strong\s*wind|heat\s*wave|cold\s*wave|fine\s*dust)",
        hay, re.I
    )
    caution_hit = re.search(
        r"(주의|주의보|경보|특보|경계|위험|유의|조심|advisory|watch|warning|alert|caution|danger|notice|발효|발령)",
        hay, re.I
    )
    soft_weather_caution = (
        re.search(r"(으로\s*인한|예상|가능|우려|발생)", hay) is not None
        or re.search(r"(우박|적설|강풍|폭설|한파)[^\n]{0,6}시(?:\s|,|:|\.|…|·|-|$)", hay) is not None
    )
    if weather_hit and (caution_hit or soft_weather_caution):
        return "기상 악화 주의 안내"
    if weather_hit:
        return "기상 관련 안내"

    # 5) 동물 공격성 증가
    aggression_hit = (
        re.search(r"(공격성|공격적|사납|위협적|aggressive|attack(s)?|biting|charging)", hay)
        and re.search(r"(증가|높아졌|상승|급증|spike|uptick|빈번|더\s*자주)", hay)
    )
    if aggression_hit:
        return "동물 공격성 증가 주의"

    # 6) 신고 급증
    report_surge_hit = (
        re.search(r"(신고|제보|report(s)?)", hay)
        and re.search(r"(다수|급증|폭증|많음|많이|many|surge|spike|sudden\s*increase)", hay)
    )
    if report_surge_hit:
        return "신고 급증 주의"

    # 7) 일반 주의/위험
    if caution_hit:
        return "주의/위험 안내"

    # 8) 위치 정보 수정
    if (re.search(r"(위치|gps|좌표|geolocation|location|정확도)", hay)
        and re.search(r"(수정|해결|고침|fix|fixed|patch|정정|보완|버그\s*수정|오류\s*수정)", hay)):
        return "위치 정보 오류 수정 안내"

    # 9) 신규 기능
    if re.search(r"(신규\s*기능|새로운\s*기능|feature|기능\s*추가|added|add(ed)?\s+feature|beta\s+feature)", hay):
        return "새로운 기능 추가 안내"

    # 10) 점검/업데이트/정책/이벤트
    if re.search(r"(점검|maintenance)", hay):
        return "서비스 점검 안내"
    if re.search(r"(업데이트|release|버전|패치\s*노트|patch)", hay):
        return "업데이트 안내"
    if re.search(r"(정책|약관|privacy|policy)", hay):
        return "정책 변경 안내"
    if re.search(r"(이벤트|event|캠페인|campaign)", hay):
        return "이벤트 안내"

    # 11) 산불 주의
    wildfire_hit = (
        re.search(r"(산불|산림\s*화재|임야\s*화재|들불|forest\s*fire|wild\s*fire|bush\s*fire)", hay)
        or re.search(r"(red\s*flag\s*warning|건조\s*(주의보|경보|특보)|화재\s*위험\s*(지수|경보)|불조심)", hay)
    )
    if wildfire_hit:
        return "산불 주의 안내"

    # 12) 환경/정화/무단투기
    cleanup_hit = re.search(r"(정화\s*활동|클린업|clean[-\s]?up|cleanup)", hay)
    litter_hit = re.search(
        r"(쓰레기|무단\s*투기|illegal\s*dumping|litter|trash|garbage|waste|폐기물|담배꽁초|플라스틱|비닐|재활용|recycl(e|ing))",
        hay
    )
    environment_hit = re.search(
        r"(환경\s*보호|환경\s*캠페인|환경\s*오염|eco|sustainability|탄소\s*(중립|감축)|탄소\s*배출)",
        hay
    )

    if cleanup_hit:
        return "환경 정화 활동 안내"
    if litter_hit and re.search(r"(주의|단속|제보|신고|경고|warning|alert)", hay):
        return "쓰레기/무단 투기 주의"
    if litter_hit or environment_hit:
        return "환경 보호 안내"

    # 13) 상태 변경만 포착됐을 때의 기본값 (프론트엔드에는 없지만 서버에서 보완)
    if (status_change or "").strip():
        return "상태 변경 안내"

    # 14) 최종 기본
    return (title or "공지").strip() or "공지"

def _type_label_kor(t: str) -> str:
    m = {
        "maintenance": "서비스 점검 안내",
        "outage": "서비스 장애 안내",
        "recovery": "서비스 정상화 안내",
        "release": "업데이트 안내",
        "policy": "정책 변경 안내",
        "event": "이벤트 안내",
        "location_fix": "위치 정보 오류 수정 안내",
        "new_feature": "새로운 기능 추가 안내",
        "weather_alert": "기상 악화 주의 안내",
        "animal_aggression": "동물 공격성 증가 주의",
        "report_surge": "신고 급증 주의",
        "safety_alert": "주의/위험 안내",
        "wildfire_alert": "산불 주의 안내",
        "environment": "환경 보호 안내",
        "cleanup": "환경 정화 활동 안내",
        "litter": "쓰레기/무단 투기 주의",
    }
    return m.get((t or "").strip().lower(), "")

def _enrich_notice(n):
    rep = getattr(n, "report", None)
    usr = getattr(n, "user", None)

    body = _notif_content(n)

    title_suggest = _title_suggest_from_fields(
        notice_type=(getattr(n, "type", "") or ""),
        reply=(getattr(n, "reply", "") or ""),
        status_change=(getattr(n, "status_change", "") or ""),
        title=_notif_title(n),   # ← 원래 제목(신고ID 섞일 수 있음)
        content=body,
    )

    return {
        "id": n.id,
        "type": getattr(n, "type", "") or "",
        "type_label": _type_label_kor(getattr(n, "type", "") or ""),   # ✅ 추가
        "scope": _notif_scope(n),
        "created_at": _dt_iso(getattr(n, "created_at", None)) or "",
        "report_id": getattr(rep, "id", None),
        "user_id": getattr(usr, "id", None),
        "user_name": _user_display_name(usr),
        "animal_name": _animal_display_name(rep),
        "reply": getattr(n, "reply", "") or "",
        "status_change": getattr(n, "status_change", "") or "",
        "content": body,
        "body": body,
        "title": _notif_title(n),             # 원본(신고ID가 포함될 수 있음)
        "title_suggest": title_suggest,       # 정규 제목 후보
        "title_display": title_suggest,       # ✅ 프론트가 바로 쓰는 표시 제목
    }

# ─────────────────────────────────────
# 페이지 렌더
# ─────────────────────────────────────

@user_passes_test(_is_staff)
@with_admin_jwt_cookies
def page_settings(request):
    return render(request, "dashboard/settings.html")

@user_passes_test(_is_staff)
@with_admin_jwt_cookies
@ensure_csrf_cookie
def page_cctv(request):
    """
    예전 'dashboard_home'에서 쓰던 CCTV 데모 화면을 그대로 렌더.
    """
    devices = [
        type('D', (), {'name': 'CCTV 1', 'status': 'ONLINE'})(),
        type('D', (), {'name': 'CCTV 2', 'status': 'OFFLINE'})(),
        type('D', (), {'name': 'CCTV 3', 'status': 'OFFLINE'})(),
        type('D', (), {'name': 'CCTV 4', 'status': 'OFFLINE'})(),
    ]
    sensors = [
        type('S', (), {'device': devices[0], 'status': '감지됨'})(),
        type('S', (), {'device': devices[1], 'status': '오프라인'})(),
        type('S', (), {'device': devices[2], 'status': '오프라인'})(),
        type('S', (), {'device': devices[3], 'status': '오프라인'})(),
    ]
    return render(request, "dashboard/cctv.html", {
        "devices": devices,
        "sensors": sensors,
        "video_url": "/static/dashboard/videos/sample.mp4",
    })

@user_passes_test(_is_staff)
@with_admin_jwt_cookies
def page_home(request):
    """
    새 홈 화면(카드/그리드). 최근 공지 + KPI 통계 간단 요약 + 서버 배너
    """
    # 최근 공지
    rows = []
    if HAS_NOTIFICATION and Notification is not None:
        qs = Notification.objects.all()
        rels = []
        uf = _notif_user_field(Notification)
        if uf: rels.append(uf)
        rels += ["admin", "report", "reply"]  # 존재하는 것만 select_related
        qs = safe_select_related(qs, Notification, rels)
        order_key = "-created_at" if _model_has_field(Notification, "created_at") else "-id"
        qs = qs.order_by(order_key)[:10]
        rows = [_enrich_notice(n) for n in qs]

    # KPI 통계
    qs_r = Report.objects.all()
    total = qs_r.count()

    date_field = "report_date" if _model_has_field(Report, "report_date") else (
        "created_at" if _model_has_field(Report, "created_at") else None
    )
    if date_field:
        today_cnt = qs_r.filter(**{f"{date_field}__date": timezone.localdate()}).count()
    else:
        today_cnt = 0

    # 일관화: UNRESOLVED_STATUSES / RESOLVED_STATUSES 사용
    unresolved = qs_r.filter(status__in=UNRESOLVED_STATUSES).count()
    handled = qs_r.filter(status__in=RESOLVED_STATUSES).count()
    rate = int((handled * 100) / total) if total > 0 else 0

    s = _settings_singleton()
    server_banner = (
        s.maintenance_message
        if getattr(s, "show_server_banner", False) and getattr(s, "maintenance_message", "")
        else ""
    )

    ctx = {
        "notices": rows,
        "stats": {
            "total": total,
            "today": today_cnt,
            "unresolved": unresolved,
            "handled": handled,
            "rate": rate,
        },
        "server_banner": server_banner,
    }
    return render(request, "dashboard/home.html", ctx)

@user_passes_test(_is_staff)
@with_admin_jwt_cookies
def page_reports(request):
    return render(request, "dashboard/reports.html")

@user_passes_test(_is_staff)
@with_admin_jwt_cookies
def page_analytics(request):
    return render(request, "dashboard/analytics.html")

@user_passes_test(_is_staff)
@with_admin_jwt_cookies
def page_contents(request):
    """
    콘텐츠 템플릿 목록 페이지
    - 초기 1회용 access 토큰을 템플릿에 주입
    """
    token = str(AccessToken.for_user(request.user))  # ✅ 초기 JWT
    return render(request, "dashboard/contents/index.html", {"admin_api_token": token})

@user_passes_test(_is_staff)
@with_admin_jwt_cookies
def page_users(request):
    return render(request, "dashboard/users.html")

@user_passes_test(_is_staff)
@with_admin_jwt_cookies
def page_notices(request):
    """
    공지 목록 페이지 (SSR).
    - user/admin/report는 select_related (앞방향 FK)
    - reply가 진짜 FK/OneToOne일 때만 select_related('reply')
    - Feedback이 있으면 서브쿼리로 'reply_text'를 annotate (가장 최근 피드백 본문)
    """
    if not HAS_NOTIFICATION or Notification is None:
        return render(request, "dashboard/notices.html", {"notices": []})

    # 1) 기본 관계 미리 불러오기
    qs = Notification.objects.select_related("user", "admin", "report")

    # 2) reply가 관계 필드일 때만 select_related
    if _is_select_related_candidate(Notification, "reply"):
        qs = qs.select_related("reply")

    # 3) 최근 피드백 본문 주입 (가능할 때만)
    sq = _latest_feedback_content_subquery()
    if sq is not None and _model_has_field(Notification, "report"):
        qs = qs.annotate(reply_text=sq)

    # 4) 정렬/슬라이스는 마지막
    qs = qs.order_by("-id")

    # 5) 렌더 변환
    rows = []
    for n in qs:
        rows.append(_enrich_notice(n))

    return render(request, "dashboard/notices.html", {"notices": rows})

# ─────────────────────────────────────
# CCTV 스트리밍/분류 데모
# ─────────────────────────────────────

def frame_gen(cap):
    classifier = SingletonClassifier()
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        label, score = classifier.predict_bgr(frame)
        text = f"{label} ({score*100:.2f}%)"
        cv2.putText(frame, text, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2, cv2.LINE_AA)
        _, buffer = cv2.imencode('.jpg', frame)
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

def cctv_stream(request):
    url = request.GET.get("url", "0")
    cap = cv2.VideoCapture(int(url) if url.isdigit() else url)
    return StreamingHttpResponse(
        frame_gen(cap),
        content_type='multipart/x-mixed-replace; boundary=frame'
    )

@require_http_methods(["POST"])
def classify_image(request):
    if "file" in request.FILES:
        uploaded = request.FILES["file"]
        return JsonResponse({"ok": True, "filename": uploaded.name})
    return JsonResponse({"ok": False, "error": "No file"}, status=400)

def cctv_devices_api(request):
    data = [
        {"id": 1, "name": "CCTV 1", "online": True},
        {"id": 2, "name": "CCTV 2", "online": False},
        {"id": 3, "name": "CCTV 3", "online": False},
        {"id": 4, "name": "CCTV 4", "online": False},
    ]
    return JsonResponse(data, safe=False)

def cctv_sensors_api(request):
    data = [
        {"id": 1, "name": "CCTV 1", "detected": True},
        {"id": 2, "name": "CCTV 2", "detected": False},
        {"id": 3, "name": "CCTV 3", "detected": False},
        {"id": 4, "name": "CCTV 4", "detected": False},
    ]
    return JsonResponse(data, safe=False)

# ─────────────────────────────────────
# 설정 API
# ─────────────────────────────────────

@require_http_methods(["GET", "PUT"])
@staff_required_json
@with_admin_jwt_cookies
def api_settings(request):
    s = _settings_singleton()

    if request.method == "GET":
        return JsonResponse({
            "show_server_banner":  getattr(s, "show_server_banner", False),
            "default_region":      getattr(s, "default_region", "") or "",
            "auto_refresh_min":    getattr(s, "auto_refresh_min", 10) or 10,
            "page_size":           getattr(s, "page_size", 20) or 20,
            "default_period":      getattr(s, "default_period", "all") or "all",
            "default_sort":        getattr(s, "default_sort", "-report_date") or "-report_date",
            "unresolved_statuses": getattr(s, "unresolved_statuses", []) or [],
            "aging_threshold_days":getattr(s, "aging_threshold_days", 3) or 3,
            "notify_status_change":getattr(s, "notify_status_change", False),
            "notify_sound":        getattr(s, "notify_sound", True),
            "notify_desktop":      getattr(s, "notify_desktop", False),
            "quiet_hours_start":   s.quiet_hours_start.isoformat() if getattr(s, "quiet_hours_start", None) else None,
            "quiet_hours_end":     s.quiet_hours_end.isoformat()   if getattr(s, "quiet_hours_end", None)   else None,
            "date_format":         getattr(s, "date_format", "YYYY-MM-DD HH:mm") or "YYYY-MM-DD HH:mm",
            "mask_reporter":       getattr(s, "mask_reporter", True),
            "maintenance_mode":    getattr(s, "maintenance_mode", False),
            "maintenance_message": getattr(s, "maintenance_message", "") or "",
            "map_provider":        getattr(s, "map_provider", "kakao") or "kakao",
            "map_api_key":         getattr(s, "map_api_key", "") or "",
            "server_ping_interval_sec": getattr(s, "server_ping_interval_sec", 10),
            "log_retention_days":       getattr(s, "log_retention_days", 30),
            "db_backup_interval_hours": getattr(s, "db_backup_interval_hours", 24),
            "db_backup_dir":            getattr(s, "db_backup_dir", "backups"),
            "auto_stale_days_to_pending": getattr(s, "auto_stale_days_to_pending", 3),
            "auto_stale_target_status":   getattr(s, "auto_stale_target_status", "대기"),
            "stats_refresh_interval_min": getattr(s, "stats_refresh_interval_min", 10),
            "completed_report_retention_days": getattr(s, "completed_report_retention_days", 180),
        })

    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return HttpResponseBadRequest("invalid json")

    def to_bool(key, default=False): return bool(data.get(key, default))
    def to_int(key, default=0):
        try: return int(data.get(key, default))
        except Exception: return default
    def to_str(key, default=""):
        v = data.get(key, default)
        return v if isinstance(v, str) else default
    def to_list(key):
        v = data.get(key) or []
        return v if isinstance(v, list) else []
    def to_time_str(key):
        v = data.get(key)
        return v if (isinstance(v, str) and v) else None
    def to_time_obj(v):
        if not v: return None
        try:
            parts = [int(x) for x in v.split(":")]
            while len(parts) < 3: parts.append(0)
            return time(parts[0], parts[1], parts[2])
        except Exception:
            return None

    s.show_server_banner   = to_bool("show_server_banner", getattr(s, "show_server_banner", False))
    s.default_region       = to_str("default_region", s.default_region)
    s.auto_refresh_min     = max(1, to_int("auto_refresh_min", getattr(s, "auto_refresh_min", 10)))
    s.page_size            = max(1, to_int("page_size", getattr(s, "page_size", 20)))
    s.default_period       = to_str("default_period", getattr(s, "default_period", "all"))
    s.default_sort         = norm_sort(to_str("default_sort", getattr(s, "default_sort", "-report_date")))
    s.unresolved_statuses  = to_list("unresolved_statuses")
    s.aging_threshold_days = max(0, to_int("aging_threshold_days", getattr(s, "aging_threshold_days", 3)))
    s.notify_status_change = to_bool("notify_status_change", getattr(s, "notify_status_change", False))
    s.notify_sound         = to_bool("notify_sound", getattr(s, "notify_sound", True))
    s.notify_desktop       = to_bool("notify_desktop", getattr(s, "notify_desktop", False))
    s.quiet_hours_start    = to_time_obj(to_time_str("quiet_hours_start"))
    s.quiet_hours_end      = to_time_obj(to_time_str("quiet_hours_end"))
    s.date_format          = to_str("date_format", getattr(s, "date_format", "YYYY-MM-DD HH:mm"))
    s.mask_reporter        = to_bool("mask_reporter", getattr(s, "mask_reporter", True))
    s.maintenance_mode     = to_bool("maintenance_mode", getattr(s, "maintenance_mode", False))
    s.maintenance_message  = to_str("maintenance_message", getattr(s, "maintenance_message", ""))
    s.map_provider         = to_str("map_provider", getattr(s, "map_provider", "kakao"))
    s.map_api_key          = to_str("map_api_key", getattr(s, "map_api_key", ""))
    s.server_ping_interval_sec = max(1, to_int("server_ping_interval_sec", getattr(s, "server_ping_interval_sec", 10)))
    s.log_retention_days       = to_int("log_retention_days", getattr(s, "log_retention_days", 30))
    s.db_backup_interval_hours = max(1, to_int("db_backup_interval_hours", getattr(s, "db_backup_interval_hours", 24)))
    s.db_backup_dir            = to_str("db_backup_dir", getattr(s, "db_backup_dir", "backups"))
    s.auto_stale_days_to_pending = max(1, to_int("auto_stale_days_to_pending", getattr(s, "auto_stale_days_to_pending", 3)))
    s.auto_stale_target_status   = to_str("auto_stale_target_status", getattr(s, "auto_stale_target_status", "대기"))
    s.stats_refresh_interval_min = max(1, to_int("stats_refresh_interval_min", getattr(s, "stats_refresh_interval_min", 10)))
    s.completed_report_retention_days = max(1, to_int("completed_report_retention_days", getattr(s, "completed_report_retention_days", 180)))
    s.save()
    return api_settings(request)

# ---[ 자동 갱신용: 관리자에게 새 access 토큰 발급 ]---
@user_passes_test(_is_staff)
@require_POST
def api_issue_admin_token(request):
    """
    대시보드에서 토큰 만료 임박/만료 시 새 access 토큰을 재발급한다.
    (세션은 쓰지 않음. 관리자 로그인 상태의 서버 view이므로 안전.)
    """
    token = str(AccessToken.for_user(request.user))
    return JsonResponse({"access": token})

# ─────────────────────────────────────
# 대시보드용 신고 API
# ─────────────────────────────────────

DONE_STATUSES = {"처리완료", "완료", "종료", "무효"}

@require_http_methods(["GET"])
@staff_required_json
def api_report_stats(request):
    qs = Report.objects.all()
    total = qs.count()

    date_field = "report_date" if _model_has_field(Report, "report_date") else (
        "created_at" if _model_has_field(Report, "created_at") else None
    )

    if date_field:
        today_filter = {f"{date_field}__date": timezone.localdate()}
        today_cnt = qs.filter(**today_filter).count()
    else:
        today_cnt = 0

    # ✅ 미해결: checking + on_hold
    unresolved = qs.filter(status__in=UNRESOLVED_STATUSES).count()

    # ✅ 처리율: 완료/전체 (필요 시 RESOLVED_STATUSES에 rejected/거절/반려 포함)
    completed = qs.filter(status__in=RESOLVED_STATUSES).count()
    rate = round((completed * 100.0 / total), 1) if total else 0.0

    payload = {"total": total, "today": today_cnt, "unresolved": unresolved, "rate": rate}

    if request.GET.get("debug") in ("1", "true", "yes"):
        from django.conf import settings
        payload["_debug"] = {
            "db_name": str(settings.DATABASES["default"]["NAME"]),
            "model": f"{Report._meta.app_label}.{Report._meta.model_name}",
            "db_table": Report._meta.db_table,
            "exists": qs.exists(),
            "sample_ids": list(qs.order_by("-id").values_list("id", flat=True)[:3]),
        }
    return JsonResponse(payload, json_dumps_params={"ensure_ascii": False})

@require_http_methods(["GET"])
@staff_required_json
def api_reports(request):
    s = _settings_singleton()
    q = (request.GET.get("q") or "").strip()
    page = int(request.GET.get("page") or 1)
    page_size = int(request.GET.get("page_size") or getattr(s, "page_size", 20) or 20)
    offset = (page - 1) * page_size

    if _model_has_field(Report, "report_date"):
        allowed = ("-report_date", "report_date")
    elif _model_has_field(Report, "created_at"):
        allowed = ("-created_at", "created_at")
    else:
        allowed = ("-id", "id")
    order = getattr(s, "default_sort", allowed[0])
    if order not in allowed:
        order = allowed[0]

    related = ["animal", "user"]
    if _model_has_field(Report, "location"):
        related.append("location")
    qs = Report.objects.select_related(*related).order_by(order)

    if q:
        filters = (
            Q(status__icontains=q) |
            Q(user__username__icontains=q) | Q(user__email__icontains=q) |
            Q(animal__name_kor__icontains=q) | Q(animal__name__icontains=q)
        )
        if _model_has_field(Report, "report_region"):
            filters |= Q(report_region__icontains=q)
        elif _model_has_field(Report, "region"):
            filters |= Q(region__icontains=q)
        elif _model_has_field(Report, "address"):
            filters |= Q(address__icontains=q)
        qs = qs.filter(filters)

    total = qs.count()
    items = qs[offset: offset + page_size]

    results = []
    for r in items:
        dt = _date_value(r)
        results.append({
            "id": r.id,
            "title": getattr(r, "title", "") or "",
            "animal": _animal_label(r),
            "region": _region_value(r),
            "status": getattr(r, "status", "") or "",
            "created_at": timezone.localtime(dt).strftime("%Y-%m-%d %H:%M") if dt else "",
            "reporter": _reporter_name_or_user(r),           # ✅ 사용자 표시
            "image_url": _first_image_field_url(r, request), # ✅ 이미지 URL
        })

    return JsonResponse({
        "results": results,
        "page": page,
        "total_pages": (total + page_size - 1) // page_size,
        "total": total
    }, json_dumps_params={"ensure_ascii": False})

@require_http_methods(["GET"])
@staff_required_json
def api_reporters(request):
    top_n = int(request.GET.get("limit") or 10)
    agg = (Report.objects
           .values("user__username")
           .annotate(count=Count("id"))
           .order_by("-count")[:top_n])
    results = [{"name": (row["user__username"] or "익명"), "count": row["count"]} for row in agg]
    return JsonResponse({"results": results}, json_dumps_params={"ensure_ascii": False})

# ─────────────────────────────────────
# 사용자 API
# ─────────────────────────────────────

@login_required
@with_admin_jwt_cookies
def users_page(request):
    return render(request, "dashboard/users.html")

@login_required
def api_users(request):
    """
    GET /dashboard/api/users/?page=1&page_size=20&q=검색어
    -> 사용자 리스트 (users.html의 리스트 테이블에서 사용)
    """
    try:
        page = int(request.GET.get("page") or 1)
    except ValueError:
        page = 1
    try:
        page_size = int(request.GET.get("page_size") or 20)
    except ValueError:
        page_size = 20

    q = (request.GET.get("q") or "").strip()

    qs = User.objects.all().order_by("-id")
    if q:
        qs = qs.filter(
            Q(username__icontains=q)
            | Q(email__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
        )

    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(page)

    def _role(u: AuthUser) -> str:
        if u.is_superuser:
            return "admin"
        if u.is_staff:
            return "staff"
        return "user"

    def _display_name(u: AuthUser) -> str:
        full = u.get_full_name()
        if full:
            return full
        if u.username:
            return u.username
        if u.email:
            return u.email.split("@")[0]
        return f"user-{u.id}"

    rows = []
    for u in page_obj.object_list:
        joined = ""
        if u.date_joined:
            dj = timezone.localtime(u.date_joined)
            joined = dj.strftime("%Y-%m-%d %H:%M")
        rows.append(
            {
                "id": u.id,
                "name": _display_name(u),
                "email": u.email or "",
                "role": _role(u),
                "joined": joined,
            }
        )

    payload = {
        "count": paginator.count,
        "page": page_obj.number,
        "page_size": page_size,
        "results": rows,
    }
    return JsonResponse(payload, json_dumps_params={"ensure_ascii": False})


@require_GET
@staff_required_json
def api_user_detail(request, user_id: int):
    """
    GET /dashboard/api/users/<id>/
    -> users.html 우측 드로어에서 사용하는 상세 JSON
    """
    user = get_object_or_404(User, pk=user_id)

    # 1) 이 사용자가 신고한 Report queryset
    if _model_has_field(Report, "user"):
        qs_user_reports = Report.objects.filter(user_id=user.id)
    elif _model_has_field(Report, "reporter"):
        qs_user_reports = Report.objects.filter(reporter_id=user.id)
    else:
        qs_user_reports = Report.objects.none()

    now = timezone.now()
    thirty_days_ago = now - timedelta(days=30)

    # 날짜 필드 자동 선택
    if _model_has_field(Report, "report_date"):
        date_field = "report_date"
    elif _model_has_field(Report, "created_at"):
        date_field = "created_at"
    else:
        date_field = None

    # ---- 기본 통계 ----
    total_reports = qs_user_reports.count()
    last30_reports = 0
    if date_field:
        last30_reports = qs_user_reports.filter(
            **{f"{date_field}__gte": thirty_days_ago}
        ).count()

    # ---- 동물 Top3 (analytics와 동일 Coalesce 규칙) ----
    coalesce_exprs = []
    if _model_has_field(Report, "animal_name"):
        coalesce_exprs.append(F("animal_name"))
    if _animal_model_has("name_kor"):
        coalesce_exprs.append(F("animal__name_kor"))
    if _animal_model_has("name"):
        coalesce_exprs.append(F("animal__name"))
    coalesce_exprs.append(Value("미상", output_field=CharField()))

    by_animal_top = []
    if qs_user_reports.exists():
        rows = (
            qs_user_reports.annotate(label=Coalesce(*coalesce_exprs))
            .values("label")
            .annotate(c=Count("id"))
            .order_by("-c", "label")[:3]
        )
        by_animal_top = [[(r["label"] or "미상"), int(r["c"])] for r in rows]

    # ---- 지역 Top3 (간단 버전: _region_value 기반 파이썬 집계) ----
    by_region_top = []
    if qs_user_reports.exists():
        pairs = {}
        qs_for_region = qs_user_reports
        if _model_has_field(Report, "location"):
            qs_for_region = qs_for_region.select_related("location")
        for rpt in qs_for_region:
            lb = _region_value(rpt) or "미상"
            pairs[lb] = pairs.get(lb, 0) + 1
        region_all = sorted(pairs.items(), key=lambda x: x[1], reverse=True)
        by_region_top = [[name, cnt] for name, cnt in region_all[:3]]

    # ---- 최근 신고 5건 ----
    if date_field:
        recent_qs = qs_user_reports.order_by(f"-{date_field}")[:5]
    else:
        recent_qs = qs_user_reports.order_by("-id")[:5]

    recent = []
    for rpt in recent_qs:
        # 동물 라벨
        animal_lb = getattr(rpt, "animal_name", None)
        if not animal_lb and getattr(rpt, "animal_id", None):
            a = getattr(rpt, "animal", None)
            if a is not None:
                animal_lb = (
                    getattr(a, "name_kor", None)
                    or getattr(a, "name", None)
                    or getattr(a, "common_name", None)
                )
        if not animal_lb:
            animal_lb = "미상"

        # 날짜/시간 문자열
        dt = None
        if date_field:
            dt = getattr(rpt, date_field, None)
        if dt and timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        datetime_str = dt.isoformat() if dt else ""

        # 지역 라벨
        region_lb = _region_value(rpt) or ""

        title = (
            getattr(rpt, "title", None)
            or getattr(rpt, "summary", None)
            or getattr(rpt, "description", None)
            or ""
        )

        recent.append(
            {
                "id": rpt.id,
                "title": title,
                "animal": animal_lb,
                "status": getattr(rpt, "status", "") or "",
                "datetime": datetime_str,
                "region": region_lb,
            }
        )

    # ---- 로그인/이메일 정보(필요하면 수정 가능) ----
    joined_str = (
        timezone.localtime(user.date_joined).strftime("%Y-%m-%d %H:%M")
        if user.date_joined
        else ""
    )
    last_login_iso = (
        timezone.localtime(user.last_login).isoformat()
        if user.last_login
        else ""
    )

    # 실제 이메일 인증 여부 로직이 있으면 여기서 변경
    email_verified = False

    data = {
        "user": {
            "id": user.id,
            "name": user.get_full_name()
            or user.username
            or (user.email.split("@")[0] if user.email else ""),
            "email": user.email or "",
            "is_active": user.is_active,
            "date_joined": joined_str,
            "last_login": last_login_iso,
            "groups": [g.name for g in user.groups.all()],
        },
        "stats": {
            "total_reports": total_reports,
            "last30_reports": last30_reports,
            "active_sessions": 0,  # 세션 추적 안 하면 0 고정
        },
        "email_verification": {"verified": email_verified},
        "activity": {
            "total_reports": total_reports,
            "recent_30d": last30_reports,
            "by_animal_top": by_animal_top,
            "by_region_top": by_region_top,
            "recent": recent,
        },
        "logins": {
            "act_sessions": 0,
            "active_sessions": 0,
        },
    }
    return JsonResponse(data, json_dumps_params={"ensure_ascii": False})

def _model_has_field(model, name: str) -> bool:
    return any(getattr(f, "name", None) == name for f in model._meta.get_fields())

def _animal_model_has(field_name: str) -> bool:
    if not _model_has_field(Report, "animal"):
        return False
    animal_model = Report._meta.get_field("animal").remote_field.model
    return any(getattr(f, "name", None) == field_name for f in animal_model._meta.get_fields())

def _animal_label_or_none(animal_obj):
    """
    Animal 객체에서 표시 텍스트를 안전하게 꺼낸다.
    name_kor > name > label > title > (없으면 None)
    """
    if not animal_obj:
        return None
    for cand in ("name_kor", "name", "label", "title"):
        v = getattr(animal_obj, cand, None)
        if v:
            return str(v)
    return None

@require_GET
@user_passes_test(_is_staff)
def user_region_top3(request, user_id):
    """
    GET /dashboard/api/users/<user_id>/region-top/
    → 특정 유저가 신고한 지역 상위 3개 반환
    """
    try:
        qs = (
            Report.objects
            .filter(user_id=user_id)
            .select_related("location")
        )
    except Exception:
        return JsonResponse({"regions": []})

    region_counts = {}

    for r in qs:
        loc = getattr(r, "location", None)
        if loc:
            for f in ("address", "region", "district", "city", "name"):
                v = getattr(loc, f, None)
                if v:
                    region = v.strip()
                    break
            else:
                region = "미상"
        else:
            region = getattr(r, "report_region", None) or "미상"

        region_counts[region] = region_counts.get(region, 0) + 1

    # 상위 3개 정렬
    top3 = sorted(region_counts.items(), key=lambda x: x[1], reverse=True)[:3]

    return JsonResponse({
        "regions": [[name, cnt] for name, cnt in top3]
    })

@require_POST
@staff_required_json
def api_users_bulk(request):
    """
    POST { action: set_role|activate|deactivate|send_reset, ids: [int,...], role?: admin|staff|user }
    """
    data = json.loads(request.body.decode("utf-8") or "{}")
    action = (data.get("action") or "").strip()
    ids = data.get("ids") or []
    if not isinstance(ids, list) or not ids:
        return JsonResponse({"ok": False, "error": "no ids"}, status=400)

    User = get_user_model()
    qs = User.objects.filter(id__in=ids)

    if action == "activate":
        qs.update(is_active=True)
        return JsonResponse({"ok": True, "updated": qs.count()})

    if action == "deactivate":
        # 자기 자신 비활성화 방지
        qs = qs.exclude(id=request.user.id)
        n = qs.update(is_active=False)
        return JsonResponse({"ok": True, "updated": n})

    if action == "set_role":
        role = (data.get("role") or "").strip()
        if role not in ("admin", "staff", "user"):
            return JsonResponse({"ok": False, "error": "invalid role"}, status=400)
        updated = 0
        for u in qs:
            if u.id == request.user.id and role != "admin":
                # 자기 자신 강등 금지
                continue
            if role == "admin":
                u.is_superuser = True; u.is_staff = True
            elif role == "staff":
                u.is_superuser = False; u.is_staff = True
            else:
                u.is_superuser = False; u.is_staff = False
            u.save(update_fields=["is_superuser", "is_staff"])
            updated += 1
        return JsonResponse({"ok": True, "updated": updated})

    if action == "send_reset":
        sent = 0
        for u in qs:
            if not u.email: continue
            try:
                token = PasswordResetTokenGenerator().make_token(u)
                # 개발용: 단순 안내 메일
                reset_link = f"{request.scheme}://{request.get_host()}/accounts/reset/{u.pk}/{token}/"
                send_mail(
                    subject="[SENCITY] 비밀번호 초기화 안내",
                    message=f"아래 링크로 비밀번호를 재설정하세요:\n{reset_link}",
                    from_email=getattr(dj_settings, "DEFAULT_FROM_EMAIL", None),
                    recipient_list=[u.email],
                    fail_silently=True,
                )
                sent += 1
            except Exception:
                pass
        return JsonResponse({"ok": True, "sent": sent})

    return JsonResponse({"ok": False, "error": "invalid action"}, status=400)


@require_POST
@staff_required_json
def api_user_toggle_active(request, user_id: int):
    User = get_user_model()
    try:
        u = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return JsonResponse({"ok": False, "error": "not found"}, status=404)
    if u.id == request.user.id:
        return JsonResponse({"ok": False, "error": "cannot toggle yourself"}, status=400)
    u.is_active = not bool(u.is_active)
    u.save(update_fields=["is_active"])
    return JsonResponse({"ok": True, "is_active": u.is_active})


@require_POST
@staff_required_json
def api_user_set_role(request, user_id: int):
    data = json.loads(request.body.decode("utf-8") or "{}")
    role = (data.get("role") or "").strip()
    if role not in ("admin", "staff", "user"):
        return JsonResponse({"ok": False, "error": "invalid role"}, status=400)
    User = get_user_model()
    try:
        u = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return JsonResponse({"ok": False, "error": "not found"}, status=404)
    if u.id == request.user.id and role != "admin":
        return JsonResponse({"ok": False, "error": "cannot demote yourself"}, status=400)
    if role == "admin":
        u.is_superuser = True; u.is_staff = True
    elif role == "staff":
        u.is_superuser = False; u.is_staff = True
    else:
        u.is_superuser = False; u.is_staff = False
    u.save(update_fields=["is_superuser","is_staff"])
    return JsonResponse({"ok": True})

@require_POST
@staff_required_json
def api_user_resend_verification(request, user_id: int):
    """
    개발/시연용: 이메일 검증 메일 재전송 (실서비스에선 전용 토큰/뷰 구성 권장)
    """
    User = get_user_model()
    try:
        u = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return JsonResponse({"ok": False, "error": "not found"}, status=404)
    if not u.email:
        return JsonResponse({"ok": False, "error": "no email"}, status=400)

    try:
        token = PasswordResetTokenGenerator().make_token(u)
        verify_link = f"{request.scheme}://{request.get_host()}/accounts/verify/{u.pk}/{token}/"
        send_mail(
            subject="[SENCITY] 이메일 인증 안내",
            message=f"이메일 인증을 완료하려면 아래 링크를 클릭하세요:\n{verify_link}",
            from_email=getattr(dj_settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[u.email],
            fail_silently=True,
        )
        return JsonResponse({"ok": True, "sent": True})
    except Exception:
        return JsonResponse({"ok": False, "sent": False}, status=500)


@require_POST
@staff_required_json
def api_user_logout_all(request, user_id: int):
    """
    대상 사용자의 모든 세션 무효화
    """
    killed = 0
    try:
        for s in Session.objects.all():
            try:
                data = s.get_decoded()
            except Exception:
                continue
            if str(data.get("_auth_user_id")) == str(user_id):
                s.delete()
                killed += 1
    except Exception:
        pass
    return JsonResponse({"ok": True, "killed": killed})


# ====== 콘텐츠 편집기(신규) ======
@user_passes_test(_is_staff)
@with_admin_jwt_cookies
def page_content_new(request):
    """
    /dashboard/contents/new/?template=weekly 같은 식으로 진입
    """
    template_key = (request.GET.get("template") or "").strip() or "blank"
    ctx = {
        "mode": "new",
        "content_id": None,
        "template_key": template_key,
        "title": "새 콘텐츠 만들기",
    }
    return render(request, "dashboard/contents/editor.html", ctx)

# ====== 콘텐츠 편집기(수정) ======
@user_passes_test(_is_staff)
@with_admin_jwt_cookies
def page_content_edit(request, content_id: int):
    """
    실제 DB 연동 전: content_id만 넘겨서 편집기 열어줌
    """
    ctx = {
        "mode": "edit",
        "content_id": content_id,
        "template_key": request.GET.get("template") or "unknown",
        "title": f"콘텐츠 편집 #{content_id}",
    }
    return render(request, "dashboard/contents/editor.html", ctx)

# ====== 템플릿 미리보기 (iframe 허용) ======
@user_passes_test(_is_staff)
@with_admin_jwt_cookies
@xframe_options_sameorigin   # ← iframe 에서 열 수 있게
def page_content_preview(request, template_key: str):
    """
    /dashboard/contents/preview/<template_key>/
    template_key: new-card | weekly | safety | event | ...
    """
    # 아주 간단한 프리뷰 데이터
    samples = {
        "new-card": {
            "title": "신규 기능 카드",
            "body": "새로 추가된 기능을 소개하는 카드입니다. 3줄 요약 + 자세히 보기.",
        },
        "weekly": {
            "title": "주간 통계 하이라이트",
            "body": "핵심 지표 3개와 라인차트를 요약해 보여줍니다.",
        },
        "safety": {
            "title": "안전 수칙 카드",
            "body": "야간 이동 시 밝은 곳을 이용하세요. 분실물은 즉시 신고!",
        },
        "event": {
            "title": "이벤트 안내",
            "body": "일시/장소/신청 버튼이 포함된 카드입니다.",
        },
    }
    data = samples.get(template_key, {
        "title": "미리보기",
        "body": "해당 템플릿 키에 대한 샘플이 없습니다.",
    })
    return render(request, "dashboard/template_preview.html", {
        "template_key": template_key,
        "data": data,
    })

# ─────────────────────────────────────
# 통계 API
# ─────────────────────────────────────

@require_GET
@staff_required_json
def api_analytics(request):
    debug = request.GET.get("debug") in ("1", "true", "yes")

    # 1) 연도 / topn 파라미터
    try:
        year = int(request.GET.get("year") or timezone.localdate().year)
    except ValueError:
        year = timezone.localdate().year

    try:
        topn = int(request.GET.get("topn") or 5)
    except ValueError:
        topn = 5
    topn = max(1, min(topn, 10))

    # 2) 사용할 날짜 필드 자동 선택
    date_field = (
        "report_date"
        if _model_has_field(Report, "report_date")
        else ("created_at" if _model_has_field(Report, "created_at") else None)
    )

    months = _month_labels_for_year(year)

    if not date_field:
        # 날짜 필드 자체가 없으면 0으로만 구성된 기본 응답
        return JsonResponse(
            {
                "year": year,
                "months": months,
                "counts": [0] * 12,
                "by_animal": [],
                "by_region": [],
                "by_animal_all": [],
                "by_animal_top": [],
                "by_animal_others": [],
                "by_region_all": [],
                "by_region_top": [],
                "by_region_others": [],
                "peak_month": None,
                "top_animal": None,
            },
            json_dumps_params={"ensure_ascii": False},
        )

    # 3) 연도 범위 필터 + 기본 queryset
    tz = timezone.get_current_timezone()
    start = datetime(year, 1, 1, 0, 0, 0, tzinfo=tz)
    end = datetime(year, 12, 31, 23, 59, 59, tzinfo=tz)
    date_range = {f"{date_field}__gte": start, f"{date_field}__lte": end}

    qs_year = Report.objects.filter(**date_range)

    # 4) 월별 집계
    monthly_qs = (
        qs_year.annotate(m=TruncMonth(date_field))
        .values("m")
        .annotate(c=Count("id"))
        .order_by("m")
    )
    month_map = {row["m"].strftime("%Y-%m"): int(row["c"]) for row in monthly_qs}
    counts = [month_map.get(mm, 0) for mm in months]

    # 5) 동물별 집계 (Coalesce 규칙)
    coalesce_exprs = []
    if _model_has_field(Report, "animal_name"):
        coalesce_exprs.append(F("animal_name"))
    if _animal_model_has("name_kor"):
        coalesce_exprs.append(F("animal__name_kor"))
    if _animal_model_has("name"):
        coalesce_exprs.append(F("animal__name"))
    coalesce_exprs.append(Value("미상", output_field=CharField()))

    animal_rows = (
        qs_year.annotate(label=Coalesce(*coalesce_exprs))
        .values("label")
        .annotate(c=Count("id"))
        .order_by("-c", "label")
    )
    animals_all = [[(r["label"] or "미상"), int(r["c"])] for r in animal_rows]
    animals_all.sort(key=lambda x: x[1], reverse=True)

    animals_top = animals_all[:topn]
    animals_others = animals_all[topn:]
    etc_sum = sum(v for _, v in animals_others)
    if etc_sum > 0:
        animals_top = animals_top + [["기타", etc_sum]]

    by_animal = animals_all[:]
    top_animal = animals_all[0][0] if animals_all else None
    if top_animal == "기타" and len(animals_all) > 1:
        top_animal = animals_all[1][0]

    # 6) 지역 집계: 문자열 필드 → Location FK → _region_value fallback
    REGION_CANDIDATES = ("report_region", "region", "address", "location_name")
    region_fields = [f for f in REGION_CANDIDATES if _model_has_field(Report, f)]
    regions_all: list[list[Any]] = []
    region_stage = "none"

    # (1) Report에 직접 붙은 문자열 필드들 우선
    if region_fields:
        try:
            whens = [
                When(
                    ~Q(**{f + "__isnull": True})
                    & ~Q(**{f: ""})
                    & ~Q(**{f: "-"}),
                    then=F(f),
                )
                for f in region_fields
            ]
            region_label = Case(
                *whens, default=Value("미상"), output_field=CharField()
            )
            rows = (
                qs_year.annotate(label=region_label)
                .values("label")
                .annotate(c=Count("id"))
                .order_by("-c", "label")
            )
            regions_all = [[(r["label"] or "미상"), int(r["c"])] for r in rows]
            region_stage = "string_fields"
        except Exception:
            regions_all = []

    # (2) 필요시 Location FK 기반 집계
    if not regions_all and _model_has_field(Report, "location_id") and HAS_LOCATION:
        try:
            loc_ids = qs_year.values_list("location_id", flat=True)
            lqs = Location.objects.filter(id__in=loc_ids)

            area_expr = Case(
                When(
                    ~Q(district__isnull=True)
                    & ~Q(district="")
                    & ~Q(district="-"),
                    then=F("district"),
                ),
                When(
                    ~Q(city__isnull=True) & ~Q(city="") & ~Q(city="-"),
                    then=F("city"),
                ),
                When(
                    ~Q(region__isnull=True)
                    & ~Q(region="")
                    & ~Q(region="-"),
                    then=F("region"),
                ),
                When(
                    ~Q(address__isnull=True) & ~Q(address=""),
                    then=F("address"),
                ),
                default=Value("미상"),
                output_field=CharField(),
            )

            rows = (
                lqs.annotate(label=area_expr)
                .values("label")
                .annotate(c=Count("id"))
                .order_by("-c", "label")
            )
            regions_all = [[(r["label"] or "미상"), int(r["c"])] for r in rows]
            region_stage = "location_fk"
        except Exception:
            regions_all = []

    # (3) 그래도 안 나오면 파이썬 fallback (_region_value)
    if not regions_all:
        counter: dict[str, int] = {}
        qs = qs_year
        if _model_has_field(Report, "location"):
            qs = qs.select_related("location")

        for rpt in qs:
            label = (_region_value(rpt) or "미상").strip() or "미상"
            counter[label] = counter.get(label, 0) + 1

        regions_all = sorted(
            [[name, cnt] for name, cnt in counter.items()],
            key=lambda x: x[1],
            reverse=True,
        )
        region_stage = "python_fallback"

    # 7) Top3 + 기타 묶기
    regions_all.sort(key=lambda x: x[1], reverse=True)
    regions_top_only = regions_all[:3]
    regions_others_only = regions_all[3:]
    r_etc_sum = sum(v for _, v in regions_others_only)
    regions_top = (
        regions_top_only + [["기타", r_etc_sum]]
        if r_etc_sum > 0
        else regions_top_only
    )

    by_region = regions_all[:]

    # 8) 최다 신고월
    peak_idx = counts.index(max(counts)) if counts else -1
    peak_month = months[peak_idx] if peak_idx >= 0 else None

    # 9) 응답 payload
    payload = {
        "year": year,
        "months": months,
        "counts": counts,
        "by_animal": by_animal,
        "by_region": by_region,
        "by_animal_all": animals_all,
        "by_animal_top": animals_top,
        "by_animal_others": animals_others,
        "by_region_all": regions_all,
        "by_region_top": regions_top,
        "by_region_others": regions_others_only,
        "peak_month": peak_month,
        "top_animal": top_animal,
    }

    if debug:
        payload["_debug"] = {
            "date_field": date_field,
            "region_stage": region_stage,
            "region_fields_found": region_fields,
            "region_topn_fixed": 3,
            "sample_region_top": regions_all[:5],
        }

    return JsonResponse(payload, json_dumps_params={"ensure_ascii": False})

def api_report_points(request):
    try:
        year_str = request.GET.get("year") or ""
        animal_q = (request.GET.get("animal") or "").strip()

        year = int(year_str) if year_str.isdigit() else timezone.now().year

        # 기본 queryset (연도 필터)
        if _model_has_field(Report, "report_date"):
            qs = Report.objects.select_related("location", "animal").filter(
                report_date__year=year
            )
        elif _model_has_field(Report, "created_at"):
            qs = Report.objects.select_related("location", "animal").filter(
                created_at__year=year
            )
        else:
            return JsonResponse([], safe=False, status=200)

        # 동물 필터 (선택)
        if animal_q:
            name_q = (
                Q(name_kor__iexact=animal_q)
                | Q(name__iexact=animal_q)
                | Q(common_name__iexact=animal_q)
                | Q(name_en__iexact=animal_q)
            )
            animal_ids = list(
                Animal.objects.filter(name_q).values_list("id", flat=True)
            )
            if animal_ids:
                qs = qs.filter(animal_id__in=animal_ids)
            else:
                qs = qs.none()

        rows = []
        for r in qs:
            loc = getattr(r, "location", None)
            if not loc:
                continue

            lat = getattr(loc, "latitude", None) or getattr(loc, "lat", None)
            lng = getattr(loc, "longitude", None) or getattr(loc, "lng", None)
            if lat is None or lng is None:
                continue

            try:
                lat = float(lat)
                lng = float(lng)
            except (TypeError, ValueError):
                continue

            region = getattr(loc, "region", None) or getattr(loc, "name", None) or ""
            addr = getattr(loc, "address", None) or getattr(loc, "addr", None) or ""

            rows.append(
                {
                    "lat": lat,
                    "lng": lng,
                    "count": 1,
                    "region": region,
                    "addr": addr,
                }
            )

        return JsonResponse(rows, safe=False, status=200)

    except Exception as e:
        import traceback

        traceback.print_exc()
        return JsonResponse({"ok": False, "error": str(e)}, status=500)

@require_GET
@staff_required_json
def month_breakdown(request):
    """
    GET /dashboard/api/analytics/month-breakdown/?year=2025&month=06
    -> {"animals":[["고라니",3],...], "regions":[["수변공원",2],...]}
    """
    # 1) 파라미터
    try:
        y = int(request.GET.get("year"))
        m = int(request.GET.get("month"))
        if not (1 <= m <= 12):
            raise ValueError
    except Exception:
        return JsonResponse({"animals": [], "regions": []})

    # 2) 사용할 날짜 필드 자동선택 (연간 API와 동일)
    if _model_has_field(Report, "report_date"):
        date_field = "report_date"
    elif _model_has_field(Report, "created_at"):
        date_field = "created_at"
    else:
        return JsonResponse({"animals": [], "regions": []})

    # 3) 월 범위 (start <= dt < next_month)
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime(y, m, 1), tz)
    if m == 12:
        end = timezone.make_aware(datetime(y + 1, 1, 1), tz)
    else:
        end = timezone.make_aware(datetime(y, m + 1, 1), tz)
    date_filter = {f"{date_field}__gte": start, f"{date_field}__lt": end}

    base_qs = Report.objects.filter(**date_filter)

    # 4) 동물 라벨 (연간 API와 동일 Coalesce 규칙)
    animal_label_exprs = []
    if _model_has_field(Report, "animal_name"):
        animal_label_exprs.append(F("animal_name"))
    if _animal_model_has("name_kor"):
        animal_label_exprs.append(F("animal__name_kor"))
    if _animal_model_has("name"):
        animal_label_exprs.append(F("animal__name"))
    animal_label_exprs.append(Value("미상", output_field=CharField()))

    animals_rows = (
        base_qs.annotate(label=Coalesce(*animal_label_exprs))
        .values("label")
        .annotate(c=Count("id"))
        .order_by("-c", "label")
    )
    animals = [[(r["label"] or "미상"), int(r["c"])] for r in animals_rows]

    # 5) 지역 라벨 (문자열 필드 → Location FK → 파이썬 fallback)
    REGION_CANDIDATES = ("report_region", "region", "address", "location_name")
    region_fields = [f for f in REGION_CANDIDATES if _model_has_field(Report, f)]
    regions = []

    # (a) 문자열 필드 우선
    if region_fields:
        try:
            whens = [
                When(
                    ~Q(**{f + "__isnull": True})
                    & ~Q(**{f: ""})
                    & ~Q(**{f: "-"}),
                    then=F(f),
                )
                for f in region_fields
            ]
            region_label = Case(
                *whens, default=Value("미상"), output_field=CharField()
            )
            rows = (
                base_qs.annotate(label=region_label)
                .values("label")
                .annotate(c=Count("id"))
                .order_by("-c", "label")
            )
            regions = [[(r["label"] or "미상"), int(r["c"])] for r in rows]
        except Exception:
            regions = []

    # (b) 필요시 Location FK
    if not regions and _model_has_field(Report, "location_id") and HAS_LOCATION:
        try:
            loc_ids = base_qs.values_list("location_id", flat=True)
            area_expr = Case(
                When(
                    ~Q(district__isnull=True)
                    & ~Q(district="")
                    & ~Q(district="-"),
                    then=F("district"),
                ),
                When(
                    ~Q(city__isnull=True) & ~Q(city="") & ~Q(city="-"),
                    then=F("city"),
                ),
                When(
                    ~Q(region__isnull=True)
                    & ~Q(region="")
                    & ~Q(region="-"),
                    then=F("region"),
                ),
                When(
                    ~Q(address__isnull=True) & ~Q(address=""),
                    then=F("address"),
                ),
                default=Value("미상"),
                output_field=CharField(),
            )
            rows = (
                Location.objects.filter(id__in=loc_ids)
                .annotate(label=area_expr)
                .values("label")
                .annotate(c=Count("id"))
                .order_by("-c", "label")
            )
            regions = [[(r["label"] or "미상"), int(r["c"])] for r in rows]
        except Exception:
            regions = []

    # (c) 파이썬 fallback
    if not regions:
        pairs = {}
        qs = base_qs
        if _model_has_field(Report, "location"):
            qs = qs.select_related("location")
        for r in qs:
            lb = _region_value(r) or "미상"
            pairs[lb] = pairs.get(lb, 0) + 1
        regions = sorted(
            [[k, v] for k, v in pairs.items()], key=lambda x: x[1], reverse=True
        )

    return JsonResponse(
        {"animals": animals, "regions": regions},
        json_dumps_params={"ensure_ascii": False},
    )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_reports(request):
    q       = request.GET.get('q', '').strip()
    status_ = request.GET.get('status', '').strip()
    from_   = request.GET.get('from', '').strip()
    to_     = request.GET.get('to', '').strip()
    page    = int(request.GET.get('page', 1))
    size    = int(request.GET.get('page_size', 20))

    qs = Report.objects.select_related('animal', 'user').all()

    if q:
        animal_q = Q()
        if _animal_model_has("name_kor"):
            animal_q |= Q(animal__name_kor__icontains=q)
        if _animal_model_has("name"):
            animal_q |= Q(animal__name__icontains=q)
        if _animal_model_has("name_eng"):
            animal_q |= Q(animal__name_eng__icontains=q)

        qs = qs.filter(
            Q(user__username__icontains=q) |
            Q(user__nickname__icontains=q) |
            Q(address__icontains=q) |
            Q(region__icontains=q) |
            Q(status__icontains=q) |
            animal_q
        )
    if status_:
        qs = qs.filter(status=status_)
    if from_:
        qs = qs.filter(created_at__date__gte=from_)
    if to_:
        qs = qs.filter(created_at__date__lte=to_)

    qs = qs.order_by('-id')  # 최신 우선

    paginator = Paginator(qs, size)
    page_obj  = paginator.get_page(page)

    ser = DashboardReportListSerializer(page_obj.object_list, many=True, context={'request': request})
    return Response({
        'page': page_obj.number,
        'total_pages': paginator.num_pages,
        'results': ser.data,
    })

# ─────────────────────────────────────
# 공지 API (/dashboard/api/notices/)
# ─────────────────────────────────────

@require_http_methods(["GET"])
@staff_required_json
def api_notices(request):
    # Notification 모델이 없거나 임포트 실패해도 200 + 빈 목록
    if not HAS_NOTIFICATION or Notification is None:
        return JsonResponse({"results": [], "page": 1, "total_pages": 1, "total": 0})

    Model = Notification

    # ── 상세 ──
    nid = (request.GET.get("id") or "").strip()
    if nid:
        try:
            nid_int = int(nid)
            # 관계 필드는 실제 있을 때만 select_related
            qs = Model.objects.all()
            uf = _notif_user_field(Model)
            rels = []
            if uf: rels.append(uf)
            rels += ["admin", "report", "reply"]
            qs = safe_select_related(qs, Model, rels)
            order_key = "-created_at" if _model_has_field(Model, "created_at") else "-id"
            n = qs.order_by(order_key).get(id=nid_int)
            return JsonResponse({"ok": True, "notice": _enrich_notice(n)}, json_dumps_params={"ensure_ascii": False})
        except Exception as e:
            # 404 대신 프런트 끊기지 않게 200 + None
            debug = (request.GET.get("debug") or "").lower() in ("1","true","yes")
            payload = {"ok": True, "notice": None}
            if debug:
                payload["error"] = f"{e.__class__.__name__}: {e}"
            return JsonResponse(payload)

    # ── 목록 ──
    try:
        q       = (request.GET.get("q") or "").strip()
        scope   = (request.GET.get("scope") or "").strip()
        ntype   = (request.GET.get("type") or "").strip()
        page    = int(request.GET.get("page") or 1)
        page_size = max(1, min(int(request.GET.get("page_size") or 20), 100))
        offset  = (page - 1) * page_size

        qs = Model.objects.all()
        uf = _notif_user_field(Model)
        rels = []
        if uf: rels.append(uf)
        rels += ["admin", "report", "reply"]
        qs = safe_select_related(qs, Model, rels)

        # scope 필터
        if scope in ("personal","PERSONAL","개인"):
            if uf: qs = qs.filter(**{f"{uf}__isnull": False})
        elif scope in ("global","GLOBAL","전체"):
            if uf: qs = qs.filter(**{f"{uf}__isnull": True})

        # type 필터
        if ntype and _model_has_field(Model, "type"):
            qs = qs.filter(type__iexact=ntype)

        # q 검색(느슨)
        if q:
            cond = Q()
            for cand in ("type","status_change","content","message","reply"):
                if _model_has_field(Model, cand):
                    cond |= Q(**{f"{cand}__icontains": q})
            if cond:
                qs = qs.filter(cond)

        order_key = "-created_at" if _model_has_field(Model, "created_at") else "-id"
        total = qs.count()
        items = [_enrich_notice(n) for n in qs.order_by(order_key)[offset: offset + page_size]]

        return JsonResponse({
            "results": items,
            "page": page,
            "total_pages": (total + page_size - 1) // page_size,
            "total": total
        }, json_dumps_params={"ensure_ascii": False})

    except Exception as e:
        # 어떤 예외도 500으로 올리지 않고 “빈 목록”으로 응답
        debug = (request.GET.get("debug") or "").lower() in ("1","true","yes")
        payload = {"results": [], "page": 1, "total_pages": 1, "total": 0}
        if debug:
            payload["error"] = f"{e.__class__.__name__}: {e}"
        return JsonResponse(payload)

@require_POST
@staff_required_json
def api_notice_push(request):
    """
    공지 푸시 전송 API
    - 유효하지 않은 토큰(NotRegistered 등)은 즉시 DB에서 삭제하고 'removed'로만 집계
    - 실제 실패만 failure에 집계 → success=1, failure=0 형태로 표시 가능
    """
    if not HAS_DEVICE_TOKEN or DeviceToken is None:
        return JsonResponse({"ok": False, "error": "no device token model"}, status=500)

# ─────────────────────────────────────
# 브로드캐스트 전송 (만료/삭제 토큰 즉시 정리)
# ─────────────────────────────────────
def _acquire_once(key: str, ttl_sec: int = 60) -> bool:
    """
    중복 호출 방지용 캐시 락. key가 존재하면 False, 없으면 True로 세팅 후 True 반환.
    """
    # add는 키가 없을 때만 성공(True), 있으면 False
    return cache.add(key, "1", timeout=ttl_sec)

@require_POST
@staff_required_json
def api_push_broadcast(request):
    """
    POST /api/push/broadcast/
    body: { "title": "...", "body": "...", "tokens": [optional], "dry_run": false }
    - tokens 없으면 DeviceToken 전체로 전송
    - '등록되지 않음/만료' 토큰은 DB에서 삭제하고 failure에는 절대 넣지 않음(removed로만 집계)
    - FCM 제한 때문에 500개 배치로 전송
    - 디버깅을 위해 실패 사유별 카운트도 함께 반환(debug=false이면 생략)
    """
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return JsonResponse({"success": 0, "failure": 0, "removed": 0})

    title = (data.get("title") or "").strip() or "알림"
    body  = (data.get("body")  or "").strip() or "새 공지 알림입니다."
    dry   = bool(data.get("dry_run", False))
    debug = bool(data.get("debug", False))
    # 👇 추가: 아이디엠포턴시 키(클라이언트에서 주면 그걸 쓰고, 없으면 서버가 생성)
    idem = (data.get("idem") or "").strip()
    if not idem:
        # 내용+분 단위 타임슬라이스 해시로 기본 키 생성 (서버 중복 클릭 방지)
        now_slice = timezone.now().strftime("%Y%m%d%H%M")
        raw = f"{title}|{body}|{now_slice}"
        idem = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    idem_key = f"push_broadcast:{idem}"
    if not _acquire_once(idem_key, ttl_sec=90):
        # 이미 같은 키로 처리 중/완료 → 재발송 막기
        return JsonResponse({"success": 0, "failure": 0, "removed": 0, "skipped": True})

    req_tokens = data.get("tokens")

    if isinstance(req_tokens, list) and req_tokens:
        raw_tokens = [str(t).strip() for t in req_tokens if str(t).strip()]
    else:
        if not HAS_DEVICE_TOKEN or DeviceToken is None:
            return JsonResponse({"success": 0, "failure": 0, "removed": 0})
        raw_tokens = list(DeviceToken.objects.values_list("token", flat=True))

    notif = messaging.Notification(title=title, body=body)

    data_only = bool(data.get("data_only", False))
    for i in range(0, len(tokens), BATCH):
        chunk = tokens[i:i + BATCH]
        if data_only:
            msg = messaging.MulticastMessage(
                tokens=chunk,
                data={
                    "type": "notice",
                    "title": title,
                    "body": body,
                    "dedup": idem,  # 👈 클라에서 중복표시 방지용
                    "click_action": "FLUTTER_NOTIFICATION_CLICK",
                },
            )
        else:
            msg = messaging.MulticastMessage(
                notification=notif,
                tokens=chunk,
                data={"type": "notice", "dedup": idem, "click_action": "FLUTTER_NOTIFICATION_CLICK"},
            )
        resp = messaging.send_multicast(msg, dry_run=dry)

    # 간단 정합성 + 중복 제거
    def _looks_valid(t: str) -> bool:
        return isinstance(t, str) and len(t) >= 50 and (" " not in t)

    tokens = sorted({t for t in raw_tokens if _looks_valid(t)})
    if not tokens:
        return JsonResponse({"success": 0, "failure": 0, "removed": 0})

    # 전송
    BATCH = 500
    success = 0
    removed = 0
    failure_other = 0

    # 디버깅 용도: 실패 사유별 카운트
    reason_counts = {}

    notif = messaging.Notification(title=title, body=body)

    for i in range(0, len(tokens), BATCH):
        chunk = tokens[i:i + BATCH]
        msg = messaging.MulticastMessage(
            notification=notif,
            tokens=chunk,
            data={"type": "notice", "click_action": "FLUTTER_NOTIFICATION_CLICK"},
        )
        resp = messaging.send_multicast(msg, dry_run=dry)

        bad_tokens = []  # 이번 배치에서 삭제 대상
        for idx, r in enumerate(resp.responses):
            if r.success:
                success += 1
                continue

            exc = getattr(r, "exception", None)

            # —— 만료/삭제/미등록 등 → 실패로 집계하지 않음(removed)
            if _is_unregistered_error(exc):
                bad_tokens.append(chunk[idx])
                # 디버그 누적
                key = "unregistered"
                reason_counts[key] = reason_counts.get(key, 0) + 1
                continue

            # 그 밖의 진짜 실패만 카운트
            failure_other += 1
            key = str(getattr(exc, "code", "") or exc.__class__.__name__ or "unknown").lower()
            reason_counts[key] = reason_counts.get(key, 0) + 1

        # 삭제(드라이런 제외)
        if bad_tokens and HAS_DEVICE_TOKEN and DeviceToken is not None and not dry:
            try:
                removed += DeviceToken.objects.filter(token__in=bad_tokens).delete()[0]
            except Exception:
                # 삭제 일부 실패해도 failure로는 돌리지 않음
                pass

    resp_payload = {
        "success": success,
        "failure": failure_other,  # ← 만료/삭제는 제외된 ‘진짜 실패’만
        "removed": removed,        # ← 이번에 정리한 토큰 수
    }
    if debug:
        resp_payload["reasons"] = reason_counts  # 원하시면 팝업에 표시해서 원인 확인

    return JsonResponse(resp_payload)

# ─────────────────────────────────────
# 배너/콘텐츠 관련
# ─────────────────────────────────────

@require_POST
@user_passes_test(_is_staff)
def create_app_banner(request):
    title = (request.POST.get("title") or "").strip() or "앱 배너 공지"

    obj = Content.objects.create(
        title=title,
        kind="앱 배너 공지",
        status_label="임시저장",
        is_live=False,
        owner=request.user,
    )

    # 전체 리다이렉트 없이, 최근 목록만 갱신하도록 신호 전파
    resp = HttpResponse(status=204)
    resp["HX-Trigger"] = '{"recent:refresh": true, "banner:refresh": true}'
    return resp

def _banner_etag_payload(qs):
    rows = [
        [b.id,
         getattr(b, "is_active", None),
         getattr(b, "starts_at", None) and int(b.starts_at.timestamp()),
         getattr(b, "ends_at", None)   and int(b.ends_at.timestamp()),
         getattr(b, "text", "")]
        for b in qs
    ]
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()

@require_GET
def api_active_banners(request):
    qs = AppBanner.objects.filter(_ab_active_q()).order_by("-priority", "-created_at", "-id")
    etag = _banner_etag_payload(qs)

    inm = request.headers.get("If-None-Match")
    if inm and inm == etag:
        resp = HttpResponse(status=304)
    else:
        data = [{"id": b.id, "text": b.text, "cta": getattr(b, "cta_url", None)} for b in qs]
        resp = JsonResponse({"results": data})

    # ⚠️ 캐시 완전 차단 + ETag 부여
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    resp["ETag"] = etag
    resp["Last-Modified"] = http_date()
    return resp

@user_passes_test(_is_staff)
@with_admin_jwt_cookies
@login_required
def active_banners_partial(request):
    items = []
    if HAS_APP_BANNER:
        from django.db.models import Q
        now = timezone.now()
        qs = AppBanner.objects.all()
        q = Q()
        if _ab_has_field("is_active"): q &= Q(is_active=True)
        if _ab_has_field("starts_at"): q &= Q(starts_at__lte=now)
        if _ab_has_field("ends_at"):   q &= (Q(ends_at__isnull=True) | Q(ends_at__gte=now))
        qs = qs.filter(q)
        order = []
        if _ab_has_field("priority"):   order.append("-priority")
        if any(getattr(f,"name",None)=="updated_at" for f in AppBanner._meta.get_fields()): order.append("-updated_at")
        order += ["-created_at","-id"]
        qs = qs.order_by(*order)
        for b in qs[:20]:
            dt = getattr(b,"updated_at",None) or getattr(b,"created_at",None)
            items.append({
                "id": b.id,
                "title": getattr(b,"text",None) or getattr(b,"title","") or "(제목 없음)",
                "updated_human": naturaltime(dt or timezone.now()),
                "unset_live_url": "dashboard:content_unset_live_appbanner",
                "edit_url": "",
            })
        return render(request, "dashboard/contents/partials/active_banners.html", {"items": items})

    # Content 폴백
    qs = Content.objects.all()
    if _model_has_field(Content,"kind"):   qs = qs.filter(kind="앱 배너 공지")
    if _model_has_field(Content,"is_live"): qs = qs.filter(is_live=True)
    order=[]
    if _model_has_field(Content,"updated_at"): order.append("-updated_at")
    if _model_has_field(Content,"created_at"): order.append("-created_at")
    order.append("-id")
    for c in qs.order_by(*order)[:20]:
        dt = getattr(c,"updated_at",None) or getattr(c,"created_at",None)
        items.append({
            "id": c.id,
            "title": getattr(c,"title","") or "(제목 없음)",
            "updated_human": naturaltime(dt or timezone.now()),
            "unset_live_url": "dashboard:content_unset_live",
            "edit_url": f"/dashboard/contents/edit/{c.id}/",
        })
    return render(request, "dashboard/contents/partials/active_banners.html", {"items": items})

@require_GET
@login_required
def recent_list(request):
    """
    최근 생성된 콘텐츠 10개를 반환하는 API.
    '앱 배너 공지'로 생성한 것도 여기서 함께 내려갑니다.
    """
    qs = Content.objects.order_by("-created_at")[:10]
    if _model_has_field(Content, "author"):
        qs = qs.select_related("author")
    elif _model_has_field(Content, "owner"):
        qs = qs.select_related("owner")

    def _item(c):
        # 필요한 필드들은 실제 모델에 맞게 조정
        return {
            "id": c.id,
            "title": getattr(c, "title", "제목 없음"),
            "kind": getattr(c, "kind", ""),  # 예: "앱 배너 공지", "안전 수칙 카드" 등
            "created_at": timezone.localtime(c.created_at).isoformat(),
            "author": getattr(c.author, "username", None) if hasattr(c, "author") else None,
            # 상세/편집/미리보기 URL은 기존 네임스페이스에 맞게 구성
            "detail_url": f"/dashboard/contents/{c.id}/",
            "edit_url": f"/dashboard/contents/{c.id}/edit/",
            "preview_url": f"/dashboard/contents/{c.id}/preview/",
        }

    data = [_item(c) for c in qs]
    return JsonResponse({"results": data})

@user_passes_test(_is_staff)
@with_admin_jwt_cookies
@login_required
def recent_list_partial(request):
    """
    최근 생성/수정 항목 10개를 보여주는 파셜.
    - 라이브(is_live=True) 먼저, 그 다음 최신(updated_at/created_at) 순으로 보여줌
    - owner/author 표시명 안전 처리
    """
    # 정렬키: is_live desc, updated_at desc, created_at desc, id desc
    order_keys = []
    if _model_has_field(Content, "is_live"):
        order_keys.append("-is_live")
    if _model_has_field(Content, "updated_at"):
        order_keys.append("-updated_at")
    if _model_has_field(Content, "created_at"):
        order_keys.append("-created_at")
    order_keys.append("-id")

    qs = Content.objects.all()

    # 소유자(있다면) 미리 로드
    owner_field = None
    for name in ("owner", "author", "user"):
        if _model_has_field(Content, name):
            owner_field = name
            break
    if owner_field:
        qs = safe_select_related(qs, Content, [owner_field])

    # 정렬 및 슬라이스
    qs = qs.order_by(*order_keys)[:10]

    def display_owner(c):
        if not owner_field:
            return ""
        ow = getattr(c, owner_field, None)
        if not ow:
            return ""
        return getattr(ow, "get_full_name", lambda: "")() or getattr(ow, "username", "") or getattr(ow, "email", "") or ""

    def best_dt(c):
        for name in ("updated_at", "created_at"):
            if _model_has_field(Content, name):
                v = getattr(c, name, None)
                if v:
                    return v
        return None

    def to_item(c):
        is_live = bool(getattr(c, "is_live", False))
        if _model_has_field(Content, "status_label"):
            status_label = getattr(c, "status_label", None) or ("공개" if is_live else "임시저장")
        else:
            status_label = ("공개" if is_live else "임시저장")

        dt = best_dt(c)
        return {
            "id": c.id,
            "title": getattr(c, "title", None) or "제목 없음",
            "kind": getattr(c, "kind", "") or "",
            "is_live": is_live,
            "status_label": status_label,
            "updated_human": naturaltime(dt or timezone.now()),
            "owner": display_owner(c),
            "edit_url": f"/dashboard/contents/edit/{c.id}/",
        }

    ctx = {
        "items": [to_item(c) for c in qs],
        "total": Content.objects.count(),
        "showing": qs.count() if hasattr(qs, "count") else len(list(qs)),
    }
    return render(request, "dashboard/contents/partials/recent_list.html", ctx)

@user_passes_test(_is_staff)
def confirm_delete(request, pk: int):
    """
    삭제 확인 팝업 파셜 (행 바로 아래에 붙는 작은 팝업)
    """
    return render(request, "dashboard/contents/partials/confirm_delete.html", {"id": pk})

@user_passes_test(_is_staff)
def close_confirm(request, pk: int):
    """
    확인 팝업만 제거(컨텐츠 변경 없음)
    """
    return HttpResponse("")  # hx-swap="outerHTML" 로 제거

@user_passes_test(_is_staff)
def delete(request, pk: int):
    method = request.POST.get("_method", request.method).upper()
    if method not in ("DELETE", "POST"):
        return HttpResponse(status=405)

    # 실제 삭제
    try:
        Content.objects.filter(pk=pk).delete()
    except Exception:
        return HttpResponse(status=400)

    # 204 + recent 갱신 트리거
    resp = HttpResponse(status=204)
    resp["HX-Trigger"] = '{"recent:refresh": true, "banner:refresh": true}'
    return resp

@require_POST
@user_passes_test(_is_staff)
def content_set_live(request, pk: int):
    try:
        obj = Content.objects.get(pk=pk)
    except Content.DoesNotExist:
        return HttpResponse(status=404)

    exclusive = request.POST.get("exclusive") in ("1","true","yes")

    # ✅ Content 측 독점 처리: 다른 배너는 모두 is_live=False
    if exclusive and _model_has_field(Content, "is_live"):
        qs = Content.objects.all()
        if _model_has_field(Content, "kind"):
            qs = qs.filter(kind="앱 배너 공지")
        qs.exclude(pk=obj.pk).update(
            **({"is_live": False} |
               ({"status_label": "임시저장"} if _model_has_field(Content, "status_label") else {}))
        )

    # 현재 항목 ON
    if _model_has_field(Content, "is_live"):
        obj.is_live = True
    if _model_has_field(Content, "status_label"):
        obj.status_label = "공개"
    obj.save()

    # --- AppBanner 동기화 ---
    if HAS_APP_BANNER and getattr(obj, "kind", "") == "앱 배너 공지":
        now = timezone.now()
        if _ab_has_field("is_active") and exclusive:
            AppBanner.objects.update(is_active=False)
        ab, created = AppBanner.objects.get_or_create(
            text=(getattr(obj, "title", "") or "").strip() or "(제목 없음)"
        )
        if _ab_has_field("is_active"): ab.is_active = True
        if _ab_has_field("starts_at") and not getattr(ab, "starts_at", None): ab.starts_at = now
        if _ab_has_field("ends_at"): ab.ends_at = None
        ab.save()

    resp = HttpResponse(status=204)
    resp["HX-Trigger"] = '{"recent:refresh": true, "banner:refresh": true}'
    return resp

@require_POST
@user_passes_test(_is_staff)
def content_unset_live(request, pk: int):
    """
    Content pk 를 받아서:
    - 해당 Content.is_live 를 False 로 내리고
    - 연결된 AppBanner 가 있으면 같이 비활성화
    """
    # 1) Content OFF
    try:
        obj = Content.objects.get(pk=pk)
    except Content.DoesNotExist:
        return HttpResponse(status=404)

    if _model_has_field(Content, "is_live"):
        obj.is_live = False
    if _model_has_field(Content, "status_label"):
        obj.status_label = "임시저장"
    obj.save()

    # 2) 연결된 AppBanner OFF
    if HAS_APP_BANNER:
        ab = None
        try:
            # FK 가 있을 때 우선 사용 (content / content_id 둘 다 커버)
            if any(getattr(f, "name", None) == "content" for f in AppBanner._meta.get_fields()):
                ab = AppBanner.objects.filter(content=obj).first()
            elif any(getattr(f, "name", None) == "content_id" for f in AppBanner._meta.get_fields()):
                ab = AppBanner.objects.filter(content_id=obj.id).first()

            # FK가 없다면 제목(text == title) 매칭으로 폴백
            if ab is None:
                title_key = (getattr(obj, "title", "") or "").strip()
                if title_key:
                    ab = AppBanner.objects.filter(text=title_key).first()
        except Exception:
            ab = None

        if ab:
            _ab_set_live(ab, False)

    resp = HttpResponse(status=204)
    resp["HX-Trigger"] = '{"recent:refresh": true, "banner:refresh": true}'
    return resp

@require_POST
@user_passes_test(_is_staff)
def content_unset_live_appbanner(request, pk: int):
    if not HAS_APP_BANNER:
        return HttpResponse(status=404)
    try:
        ab = AppBanner.objects.get(pk=pk)
    except AppBanner.DoesNotExist:
        return HttpResponse(status=404)

    _ab_set_live(ab, False)

    # 연결된 Content도 함께 끄기(있다면)
    try:
        if any(getattr(f, "name", None) == "content" for f in AppBanner._meta.get_fields()):
            c = getattr(ab, "content", None)
        else:
            cid = getattr(ab, "content_id", None)
            c = Content.objects.get(pk=cid) if cid else None
        if c:
            if _model_has_field(Content, "is_live"):
                c.is_live = False
            if _model_has_field(Content, "status_label"):
                c.status_label = "임시저장"
            c.save()
    except Content.DoesNotExist:
        pass

    resp = HttpResponse(status=204)
    resp["HX-Trigger"] = '{"recent:refresh": true, "banner:refresh": true}'
    return resp

# ─────────────────────────────────────
# 수동 감지 → 신고 등록
# ─────────────────────────────────────

@login_required
@require_POST
def manual_detection_api(request):
    """
    대시보드(관리자)가 수동으로 감지값을 신고로 등록하는 내부 API
    세션 로그인 + CSRF 보호
    """
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return HttpResponseBadRequest("invalid json")

    label = (data.get("animal") or "").strip() or "미상"
    prob  = data.get("prob")  # 0.0~1.0 범위 or None
    cam_id = int(data.get("camera_id") or 1)
    location = (data.get("location") or "").strip()
    memo = (data.get("memo") or "").strip()
    status = (data.get("status") or "checking").strip() or "checking"

    device = CCTVDevice.objects.filter(id=cam_id).first()
    lat = getattr(device, "lat", None) or 0.0
    lng = getattr(device, "lng", None) or 0.0
    region = location or (device.name if device else f"카메라 {cam_id}")

    animal_obj = Animal.objects.filter(
        Q(name__iexact=label) if _animal_model_has("name") else Q()
        | (Q(name_kor__iexact=label) if _animal_model_has("name_kor") else Q())
        | (Q(name_eng__iexact=label) if _animal_model_has("name_eng") else Q())
    ).first()
    r = Report.objects.create(
        title=f"[수동] {label} 감지",
        animal=animal_obj,
        animal_name=label,
        report_date=timezone.now(),
        status=status,
        report_region=region,
        user=request.user,
        latitude=lat,
        longitude=lng,
    )

    return JsonResponse({"ok": True, "id": r.id})

# 각 카메라 번호에 해당하는 실제 CCTV URL 매핑
EXTERNAL_CAM_SOURCES = {
    1: "rtsp://bmr_7211:bmr_72117211@192.168.35.41:554/stream1",
}


def _grab_external_frame(source_url: str) -> bytes | None:
    """
    외부 CCTV에서 단일 프레임(JPEG 바이트)을 가져오는 헬퍼.
    - RTSP: OpenCV로 한 장 캡처 후 JPEG 인코딩
    - HTTP: requests.get()으로 이미지 그대로 가져오기
    """
    try:
        # RTSP 스트림인 경우
        if isinstance(source_url, str) and source_url.startswith("rtsp://"):
            # Windows/OpenCV 안정화를 위해 MSMF 우선순위 끄기 (위에서 이미 설정했으면 중복 무관)
            os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_MSMF", "0")

            cap = cv2.VideoCapture(source_url)
            if not cap or not cap.isOpened():
                print("[CCTV][ERROR] cannot open RTSP:", source_url)
                return None

            ok, frame = cap.read()
            cap.release()
            if not ok or frame is None:
                print("[CCTV][ERROR] cannot read frame from RTSP:", source_url)
                return None

            ok, buf = cv2.imencode(".jpg", frame)
            if not ok:
                print("[CCTV][ERROR] jpeg encode failed")
                return None

            return buf.tobytes()

        # 그 외(예: HTTP 캡처 URL)는 기존 방식 유지
        resp = requests.get(
            source_url,
            timeout=5,
            headers={"Connection": "close"},
        )
        resp.raise_for_status()
        return resp.content

    except Exception as e:
        print("[CCTV][ERROR] grab frame failed:", e)
        return None


@user_passes_test(_is_staff)
@with_admin_jwt_cookies
def cctv_proxy_frame(request):
    """
    외부 CCTV에서 한 장 프레임을 대신 가져와서 반환하는 프록시.
    -> YOLO 분석용 스틸 이미지 용도

    GET /dashboard/api/cctv-proxy-frame/?cam=1
    """
    cam_no = int(request.GET.get("cam", "1"))
    source_url = EXTERNAL_CAM_SOURCES.get(cam_no)
    if not source_url:
        return HttpResponse(status=404)

    frame_bytes = _grab_external_frame(source_url)
    if not frame_bytes:
        return HttpResponse(status=502)

    # YOLO 백엔드에선 항상 JPEG로 처리하니 content_type은 고정해도 됨
    return HttpResponse(frame_bytes, content_type="image/jpeg")
