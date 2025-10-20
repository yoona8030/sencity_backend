# dashboard/views.py
import cv2
import json
import re
import html as _html
from datetime import time, datetime
from functools import wraps

from django.shortcuts import render
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.shortcuts import redirect
from django.http import JsonResponse, StreamingHttpResponse, HttpResponseBadRequest
from django.contrib.auth.decorators import user_passes_test, login_required
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser
from django.core.paginator import Paginator, EmptyPage
from django.utils import timezone
from django.utils.html import strip_tags
from django.db import models
from django.db.models import Count, Q, F, Value, Case, When, CharField, OuterRef, Subquery
from django.db.models.functions import TruncMonth, Coalesce
from django.db.models.fields.files import FieldFile
from django.views.decorators.http import require_http_methods, require_GET
from django.db.models.fields.related import ForeignObjectRel  # ← 추가

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

from .models import CCTVDevice, MotionSensor, Prediction, DashboardSetting
from dashboard.vision.adapter import SingletonClassifier

User = get_user_model()

# ─────────────────────────────────────
# 공통 헬퍼
# ─────────────────────────────────────

@login_required
def home(request):
    return render(request, 'dashboard/home.html')

@login_required
def reports(request):
    return render(request, 'dashboard/reports.html')

def _is_staff(user):
    return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))

def staff_required_json(viewfunc):
    @wraps(viewfunc)
    def _wrapped(request, *args, **kwargs):
        u = request.user
        if not (u.is_authenticated and (u.is_staff or u.is_superuser)):
            return JsonResponse({"detail": "Unauthorized"}, status=401)
        return viewfunc(request, *args, **kwargs)
    return _wrapped

def _settings_singleton() -> DashboardSetting:
    obj, _ = DashboardSetting.objects.get_or_create(id=1)
    return obj

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

# 맨 위 import 근처에 추가 (파일 상단부)
from django.db.models.fields.files import FieldFile

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

def _enrich_notice(n):
    rep = getattr(n, "report", None)
    usr = getattr(n, "user", None)

    body = _notif_content(n)

    title_suggest = _title_suggest_from_fields(
        notice_type=(getattr(n, "type", "") or ""),
        reply=(getattr(n, "reply", "") or ""),
        status_change=(getattr(n, "status_change", "") or ""),
        title=_notif_title(n),
        content=body,
    )

    return {
        "id": n.id,
        "type": getattr(n, "type", "") or "",
        "scope": _notif_scope(n),
        "created_at": _dt_iso(getattr(n, "created_at", None)) or "",
        "report_id": getattr(rep, "id", None),
        "user_id": getattr(usr, "id", None),
        "user_name": _user_display_name(usr),
        "animal_name": _animal_display_name(rep),
        "reply": getattr(n, "reply", "") or "",
        "status_change": getattr(n, "status_change", "") or "",
        "content": body,
        "title": _notif_title(n),
        "title_suggest": title_suggest,
    }

# ─────────────────────────────────────
# 페이지 렌더
# ─────────────────────────────────────

@user_passes_test(_is_staff)
def page_settings(request):
    return render(request, "dashboard/settings.html")

@user_passes_test(_is_staff)
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
def page_home(request):
    """
    새 홈 화면(카드/그리드). 최근 공지 + KPI 통계 간단 요약 + 서버 배너
    - 템플릿에서 추가 카드/표는 /dashboard/api/* 를 통해 동적으로 채운다.
    """
    # 최근 공지
    rows = []
    if HAS_NOTIFICATION and Notification is not None:
        qs = Notification.objects.select_related("user", "admin", "report")
        if _is_select_related_candidate(Notification, "reply"):
            qs = qs.select_related("reply")
        qs = qs.order_by("-id")[:10]
        rows = [_enrich_notice(n) for n in qs]

    # KPI 통계(서버 렌더 1차 표시; 클라이언트에서 /api/report-stats 로 주기적 갱신)
    qs_r = Report.objects.all()
    total = qs_r.count()

    date_field = "report_date" if _model_has_field(Report, "report_date") else (
        "created_at" if _model_has_field(Report, "created_at") else None
    )
    if date_field:
        today_cnt = qs_r.filter(**{f"{date_field}__date": timezone.localdate()}).count()
    else:
        today_cnt = 0

    unresolved = qs_r.exclude(status__in=DONE_STATUSES).count()
    handled = max(total - unresolved, 0)
    rate = int((handled * 100) / total) if total > 0 else 0

    s = _settings_singleton()
    server_banner = (
        s.maintenance_message
        if getattr(s, "show_server_banner", False) and getattr(s, "maintenance_message", "")
        else ""
    )

    ctx = {
        "notices": rows,  # 최근 공지 10건
        "stats": {        # 1차 렌더용 숫자(화면 로드 직후 즉시 보이게)
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
def page_reports(request):
    return render(request, "dashboard/reports.html")

@user_passes_test(_is_staff)
def page_analytics(request):
    return render(request, "dashboard/analytics.html")

@user_passes_test(_is_staff)
def page_contents(request):
    return render(request, "dashboard/contents.html")

@user_passes_test(_is_staff)
def page_users(request):
    return render(request, "dashboard/users.html")

@user_passes_test(_is_staff)
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

# ─────────────────────────────────────
# 설정 API
# ─────────────────────────────────────

@require_http_methods(["GET", "PUT"])
@staff_required_json
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

    s.save()
    return api_settings(request)

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

    unresolved = qs.exclude(status__in=DONE_STATUSES).count()

    payload = {"total": total, "today": today_cnt, "unresolved": unresolved}
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
def users_page(request):
    return render(request, "dashboard/users.html")

@login_required
def api_users(request):
    q = (request.GET.get("q") or "").strip()
    page = int(request.GET.get("page") or 1)
    page_size = int(request.GET.get("page_size") or 20)
    page_size = max(1, min(page_size, 100))
    order = (request.GET.get("order") or "-date_joined").strip()

    qs = User.objects.all()

    if q:
        qs = qs.filter(
            Q(email__icontains=q) |
            Q(username__icontains=q) |
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q)
        )

    try:
        qs = qs.order_by(order)
    except Exception:
        qs = qs.order_by("-date_joined")

    paginator = Paginator(qs, page_size)
    try:
        page_obj = paginator.page(page)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages if paginator.num_pages else 1)

    def role_of(u: AbstractUser) -> str:
        g = u.groups.first().name if u.groups.exists() else None
        if g:
            return g
        if getattr(u, "is_superuser", False):
            return "admin"
        if getattr(u, "is_staff", False):
            return "staff"
        return "user"

    results = [
        {
            "id": u.id,
            "name": (u.get_full_name() or u.username or "").strip(),
            "email": u.email or "",
            "role": role_of(u),
            "joined": (u.date_joined.strftime("%Y-%m-%d") if getattr(u, "date_joined", None) else ""),
        }
        for u in page_obj.object_list
    ]

    data = {
        "page": page_obj.number,
        "total_pages": paginator.num_pages,
        "count": paginator.count,
        "results": results,
    }
    return JsonResponse(data)

# ====== 콘텐츠 편집기(신규) ======
@user_passes_test(_is_staff)
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
    return render(request, "dashboard/content_editor.html", ctx)

# ====== 콘텐츠 편집기(수정) ======
@user_passes_test(_is_staff)
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
    return render(request, "dashboard/content_editor.html", ctx)

# ====== 템플릿 미리보기 (iframe 허용) ======
@user_passes_test(_is_staff)
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
    try:
        year = int(request.GET.get("year") or timezone.localdate().year)
    except ValueError:
        year = timezone.localdate().year
    try:
        topn = int(request.GET.get("topn") or 5)
    except ValueError:
        topn = 5
    topn = max(1, min(topn, 10))

    tz = timezone.get_current_timezone()
    start = datetime(year, 1, 1, 0, 0, 0, tzinfo=tz)
    end   = datetime(year, 12, 31, 23, 59, 59, tzinfo=tz)

    date_field = "report_date" if _model_has_field(Report, "report_date") else (
        "created_at" if _model_has_field(Report, "created_at") else None
    )
    months = _month_labels_for_year(year)
    if not date_field:
        return JsonResponse({
            "year": year, "months": months, "counts": [0]*12,
            "by_animal": [], "by_region": [],
            "by_animal_all": [], "by_animal_top": [], "by_animal_others": [],
            "by_region_all": [], "by_region_top": [], "by_region_others": [],
            "peak_month": None, "top_animal": None,
        }, json_dumps_params={"ensure_ascii": False})

    date_range = {f"{date_field}__gte": start, f"{date_field}__lte": end}

    monthly_qs = (
        Report.objects.filter(**date_range)
        .annotate(m=TruncMonth(date_field))
        .values("m").annotate(c=Count("id")).order_by("m")
    )
    month_map = {row["m"].strftime("%Y-%m"): int(row["c"]) for row in monthly_qs}
    counts = [month_map.get(mm, 0) for mm in months]

    coalesce_exprs = []
    if _model_has_field(Report, "animal_name"):
        coalesce_exprs.append(F("animal_name"))
    if _animal_model_has("name_kor"):
        coalesce_exprs.append(F("animal__name_kor"))
    if _animal_model_has("name"):
        coalesce_exprs.append(F("animal__name"))
    coalesce_exprs.append(Value("미상", output_field=CharField()))

    animal_rows = (
        Report.objects.filter(**date_range)
        .annotate(label=Coalesce(*coalesce_exprs))
        .values("label").annotate(c=Count("id")).order_by("-c", "label")
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

    REGION_CANDIDATES = ("report_region", "region", "address", "location_name")
    region_fields = [f for f in REGION_CANDIDATES if _model_has_field(Report, f)]
    region_stage = "none"
    regions_all = []

    if region_fields:
        try:
            whens = [
                When(~Q(**{f + "__isnull": True}) & ~Q(**{f: ""}) & ~Q(**{f: "-"}), then=F(f))
                for f in region_fields
            ]
            region_label = Case(*whens, default=Value("미상"), output_field=CharField())
            rows = (
                Report.objects.filter(**date_range)
                .annotate(label=region_label)
                .values("label").annotate(c=Count("id")).order_by("-c", "label")
            )
            regions_all = [[(r["label"] or "미상"), int(r["c"])] for r in rows]
            region_stage = "string_fields"
        except Exception:
            regions_all = []

    if not regions_all and _model_has_field(Report, "location_id") and HAS_LOCATION:
        try:
            lqs = Location.objects.filter(
                id__in=Report.objects.filter(**date_range).values("location_id")
            )
            area_expr = Case(
                When(~Q(district__isnull=True) & ~Q(district="") & ~Q(district="-"), then=F("district")),
                When(~Q(city__isnull=True)     & ~Q(city="")     & ~Q(city="-"),     then=F("city")),
                When(~Q(region__isnull=True)   & ~Q(region="")   & ~Q(region="-"),   then=F("region")),
                When(~Q(address__isnull=True)  & ~Q(address=""),                         then=F("address")),
                default=Value("미상"), output_field=CharField(),
            )
            rows = (
                lqs.annotate(label=area_expr)
                   .values("label").annotate(c=Count("id")).order_by("-c", "label")
            )
            regions_all = [[(r["label"] or "미상"), int(r["c"])] for r in rows]
            region_stage = "location_fk"
        except Exception:
            regions_all = []

    if not regions_all:
        pairs = {}
        qs = Report.objects.filter(**date_range)
        if _model_has_field(Report, "location"):
            qs = qs.select_related("location")
        for r in qs:
            lb = _region_value(r) or "미상"
            pairs[lb] = pairs.get(lb, 0) + 1
        regions_all = sorted([[k, v] for k, v in pairs.items()], key=lambda x: x[1], reverse=True)
        region_stage = "python_fallback"

    regions_all.sort(key=lambda x: x[1], reverse=True)
    regions_top_only = regions_all[:3]
    regions_others_only = regions_all[3:]
    r_etc_sum = sum(v for _, v in regions_others_only)
    regions_top = regions_top_only + [["기타", r_etc_sum]] if r_etc_sum > 0 else regions_top_only

    by_region = regions_all[:]
    peak_idx = counts.index(max(counts)) if counts else -1
    peak_month = (months[peak_idx] if peak_idx >= 0 else None)

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

    # 4) 동물 라벨 만들기 (연간 API와 동일한 Coalesce 규칙)
    animal_label_exprs = []
    if _model_has_field(Report, "animal_name"):
        animal_label_exprs.append(F("animal_name"))
    if _animal_model_has("name_kor"):
        animal_label_exprs.append(F("animal__name_kor"))
    if _animal_model_has("name"):
        animal_label_exprs.append(F("animal__name"))
    # 아무 것도 없으면 "미상"
    animal_label_exprs.append(Value("미상", output_field=CharField()))

    animals_rows = (
        base_qs
        .annotate(label=Coalesce(*animal_label_exprs))
        .values("label").annotate(c=Count("id"))
        .order_by("-c", "label")
    )
    animals = [[(r["label"] or "미상"), int(r["c"])] for r in animals_rows]

    # 5) 지역 라벨 만들기 (연간 API와 동일 단계: 문자열 필드 → location FK → 파이썬 fallback)
    REGION_CANDIDATES = ("report_region", "region", "address", "location_name")
    region_fields = [f for f in REGION_CANDIDATES if _model_has_field(Report, f)]
    regions = []

    # (a) 문자열 필드 우선
    if region_fields:
        try:
            whens = [
                When(~Q(**{f + "__isnull": True}) & ~Q(**{f: ""}) & ~Q(**{f: "-"}), then=F(f))
                for f in region_fields
            ]
            region_label = Case(*whens, default=Value("미상"), output_field=CharField())
            rows = (
                base_qs
                .annotate(label=region_label)
                .values("label").annotate(c=Count("id"))
                .order_by("-c", "label")
            )
            regions = [[(r["label"] or "미상"), int(r["c"])] for r in rows]
        except Exception:
            regions = []

    # (b) 필요시 location FK에서 파생(프로젝트에 Location이 있을 때)
    if not regions and _model_has_field(Report, "location_id") and HAS_LOCATION:
        try:
            # base_qs의 location_id만 모아 Location에서 라벨 생성
            from api.models import Location
            loc_ids = base_qs.values_list("location_id", flat=True)
            area_expr = Case(
                When(~Q(district__isnull=True) & ~Q(district="") & ~Q(district="-"), then=F("district")),
                When(~Q(city__isnull=True)     & ~Q(city="")     & ~Q(city="-"),     then=F("city")),
                When(~Q(region__isnull=True)   & ~Q(region="")   & ~Q(region="-"),   then=F("region")),
                When(~Q(address__isnull=True)  & ~Q(address=""),                         then=F("address")),
                default=Value("미상"), output_field=CharField(),
            )
            rows = (
                Location.objects.filter(id__in=loc_ids)
                .annotate(label=area_expr)
                .values("label").annotate(c=Count("id"))
                .order_by("-c", "label")
            )
            regions = [[(r["label"] or "미상"), int(r["c"])] for r in rows]
        except Exception:
            regions = []

    # (c) 끝으로 파이썬 fallback
    if not regions:
        pairs = {}
        qs = base_qs
        if _model_has_field(Report, "location"):
            qs = qs.select_related("location")
        for r in qs:
            lb = _region_value(r) or "미상"
            pairs[lb] = pairs.get(lb, 0) + 1
        regions = sorted([[k, v] for k, v in pairs.items()], key=lambda x: x[1], reverse=True)

    return JsonResponse({"animals": animals, "regions": regions}, json_dumps_params={"ensure_ascii": False})

# ─────────────────────────────────────
# 공지 API (/dashboard/api/notices/)
# ─────────────────────────────────────

@require_http_methods(["GET"])
@staff_required_json
def api_notices(request):
    if not HAS_NOTIFICATION or Notification is None:
        return JsonResponse({"results": [], "page": 1, "total_pages": 1, "total": 0})

    Model = Notification

    # 상세 조회
    nid = request.GET.get("id")
    if nid:
        try:
            nid_int = int(nid)
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": "not found"}, status=404)

        try:
            qs = Model.objects.select_related("user", "admin", "report")
            if _is_select_related_candidate(Model, "reply"):
                qs = qs.select_related("reply")
            n = qs.get(id=nid_int)
        except Model.DoesNotExist:
            return JsonResponse({"ok": False, "error": "not found"}, status=404)

        return JsonResponse({"ok": True, "notice": _enrich_notice(n)},
                            json_dumps_params={"ensure_ascii": False})

    # 목록 조회
    q = (request.GET.get("q") or "").strip()
    scope = (request.GET.get("scope") or "").strip()   # personal|global|개인|전체
    ntype = (request.GET.get("type") or "").strip()
    page = int(request.GET.get("page") or 1)
    page_size = max(1, min(int(request.GET.get("page_size") or 20), 100))
    offset = (page - 1) * page_size

    qs = Model.objects.select_related("user", "admin", "report").order_by("-id")
    if _is_select_related_candidate(Model, "reply"):
        qs = qs.select_related("reply")

    if scope in ("personal", "PERSONAL", "개인"):
        qs = qs.filter(user__isnull=False)
    elif scope in ("global", "GLOBAL", "전체"):
        qs = qs.filter(user__isnull=True)

    if ntype:
        qs = qs.filter(type__iexact=ntype)

    if q:
        qs = qs.filter(Q(type__icontains=q) | Q(status_change__icontains=q))

    total = qs.count()
    items = [_enrich_notice(n) for n in qs[offset:offset + page_size]]

    return JsonResponse({
        "results": items,
        "page": page,
        "total_pages": (total + page_size - 1) // page_size,
        "total": total
    }, json_dumps_params={"ensure_ascii": False})


