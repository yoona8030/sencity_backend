import requests, ipaddress, socket, re, json
from typing import Optional
from urllib.parse import urlparse, urlencode, unquote, urljoin
from datetime import datetime, time, timedelta, date
from PIL import Image
from django.apps import apps

from django.contrib.auth import get_user_model, authenticate
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.decorators import method_decorator
from django.conf import settings
from django.db.models import (
    Case, When, Value, CharField, F, Q, Count, Max, OuterRef, Subquery, DateTimeField
)
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.db.models.functions import ExtractYear
from django.http import StreamingHttpResponse, JsonResponse, HttpResponse, HttpResponseBadRequest
from django.views.decorators.http import require_GET
from django.views.decorators.cache import cache_page

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, viewsets, status, permissions, generics
from rest_framework.permissions import IsAuthenticated, AllowAny, IsAdminUser
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.decorators import action, api_view, permission_classes, authentication_classes
from rest_framework.response import Response
from rest_framework.request import Request
from rest_framework.views import APIView
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.authentication import get_authorization_header

try:
    from rest_framework_simplejwt.authentication import JWTAuthentication
    HAVE_JWT = True
except Exception:
    HAVE_JWT = False

from .push import send_push_only
from .ml import predict_topk, predict_topk_grouped  # 모델 유틸
from .utils import is_admin
from .utils.fcm import send_fcm_to_token, send_fcm_to_topic
from .models import (
    User, Animal, SearchHistory, Location, Report, Notification,
    Feedback, Admin, Statistic, SavedPlace, Profile, DeviceToken, AppBanner
)
from .pagination import DefaultPagination
from .serializers import (
    UserSerializer, UserSignUpSerializer,
    AnimalSerializer, SearchHistorySerializer, SearchHistoryCreateSerializer,
    LocationSerializer, ReportSerializer, ReportCreateSerializer,
    NotificationSerializer, FeedbackSerializer,
    StatisticSerializer, SavedPlaceCreateSerializer, SavedPlaceReadSerializer,
    AdminSerializer, ProfileSerializer,
    UserProfileSerializer,
    ReportNoAuthCreateSerializer, DeviceTokenSerializer,
    AppBannerActiveSerializer, AppBannerReadSerializer, AppBannerSerializer
)
from .filters import ReportFilter, NotificationFilter

User = get_user_model()

# 공통: 관리자/스태프만 허용(필요 없으면 is_authenticated만 체크로 바꾸세요)
def _is_staff(u):
    return u.is_authenticated and (u.is_staff or u.is_superuser)

def _build_image_url(request, report: Report):
    # image 필드/경로 이름이 다르면 맞게 바꾸세요(예: report.photo, report.image 등)
    img = getattr(report, 'image', None) or getattr(report, 'photo', None)
    if not img:
        return ''
    try:
        url = img.url
    except Exception:
        return ''
    return request.build_absolute_uri(url)

# ─────────────────────────────────────────────────────────────
# 공용 헬퍼: 동물 표시용 이름 필드 선택(name_kor -> name)
# ─────────────────────────────────────────────────────────────
def _animal_name_field(report_model) -> Optional[str]:
    """
    Report.animal FK가 가리키는 Animal 모델에서 표시용 이름 필드를 선택.
    우선순위: name_kor → name → (없으면 None)
    반환 예: 'animal__name_kor' / 'animal__name' / None
    """
    animal_model = report_model._meta.get_field('animal').remote_field.model
    field_names = {f.name for f in animal_model._meta.get_fields()}
    if 'name_kor' in field_names:
        return 'animal__name_kor'
    if 'name' in field_names:
        return 'animal__name'
    return None

# ─────────────────────────────────────────────────────────────
# Permissions
# ─────────────────────────────────────────────────────────────
class IsAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_staff)

class IsAdminOrReadGroup(permissions.BasePermission):
    """
    SAFE_METHODS:
      - ?type=group 목록 조회 → 비로그인 허용
      - 그 외 SAFE 조회 → 로그인 필요
      - 객체 조회: group 누구나 / individual 은 관리자 또는 본인
    비-SAFE: 관리자만
    """
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            qtype = (request.query_params.get('type') or '').lower().strip()
            if qtype == 'group':
                return True
            return bool(request.user and request.user.is_authenticated)
        return bool(request.user and request.user.is_authenticated and is_admin(request.user))

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            if getattr(obj, 'type', None) == 'group':
                return True
            if request.user and request.user.is_authenticated:
                return is_admin(request.user) or (getattr(obj, 'user_id', None) == request.user.id)
            return False
        return bool(request.user and request.user.is_authenticated and is_admin(request.user))


class IsAuthenticatedOrReadGroup(permissions.BasePermission):
    """ /notifications/?type=group → 익명 허용, 그 외 → 인증 필요 """
    def has_permission(self, request: Request, view) -> bool:
        qtype = request.query_params.get("type", "").lower()
        if qtype == "group" and request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated)

# ─────────────────────────────────────────────────────────────
# Notification 유틸
# ─────────────────────────────────────────────────────────────
def _resolve_admin_from_request_or_feedback(request, fb) -> Optional[Admin]:
    a = getattr(fb, "admin", None) if fb is not None else None
    if a is not None:
        if isinstance(a, Admin):
            return a
        if isinstance(a, User):
            return getattr(a, "admin", None)
    return getattr(request.user, "admin", None) if is_admin(request.user) else None


def _upsert_notification_for_report(
    *, report: Report, reply: Optional[str], status_change: Optional[str], admin_obj: Optional[Admin]
) -> Notification:
    """
    보고서별 개인 알림 1건 유지(업서트)
    """
    has_report_fk = any(f.name == "report" for f in Notification._meta.get_fields())
    base = Notification.objects.filter(type='individual', user_id=report.user_id)
    if has_report_fk:
        base = base.filter(report_id=report.id)

    with transaction.atomic():
        obj = base.order_by('-created_at', '-id').first()
        if obj:
            changed = False
            if reply is not None and (obj.reply or "") != reply:
                obj.reply = reply; changed = True
            if status_change is not None and (obj.status_change or "") != status_change:
                obj.status_change = status_change; changed = True
            if admin_obj is not None and (getattr(obj, 'admin_id', None) or None) != getattr(admin_obj, 'id', None):
                obj.admin = admin_obj; changed = True
            if changed:
                save_fields = []
                if reply is not None:         save_fields.append('reply')
                if status_change is not None: save_fields.append('status_change')
                if admin_obj is not None:     save_fields.append('admin')
                obj.save(update_fields=save_fields)
            return obj

        payload = dict(
            type='individual',
            user_id=report.user_id,
            reply=reply,
            status_change=status_change,
            admin=admin_obj
        )
        if has_report_fk:
            payload['report_id'] = report.id
        return Notification.objects.create(**payload)

# ─────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────
class SignUpView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = UserSignUpSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            refresh = RefreshToken.for_user(user)
            return Response({
                "token": str(refresh.access_token),
                "user_id": user.id,
                "username": user.username,
                "email": user.email,
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password')

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response(
                {'success': False, 'message': '이메일이 존재하지 않습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not user.check_password(password):
            return Response(
                {'success': False, 'message': '비밀번호가 일치하지 않습니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        refresh = RefreshToken.for_user(user)
        return Response({
            'success': True,
            'access':  str(refresh.access_token),
            'refresh': str(refresh),
            'username': user.username,
            'email': user.email,
            'user_id': user.id,
        }, status=status.HTTP_200_OK)


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdminUser]

# ─────────────────────────────────────────────────────────────
# Image Proxy (SSRF 보호) - 개선본
# ─────────────────────────────────────────────────────────────
ALLOWED_SCHEMES = {"http", "https"}

# 도메인 전체가 아니라 "접미사"로 관리 → 모든 서브도메인 허용
ALLOWED_HOST_SUFFIXES = {
    "chosun.com",          # *.chosun.com (resizer, www 등)
    "gstatic.com",         # encrypted-tbn*.gstatic.com
    "namu.wiki",
    # 필요시 추가: "daumcdn.net", "naver.net", ...
}

REQUEST_TIMEOUT = 8  # seconds

def _host_allowed(host: str) -> bool:
    host = (host or "").lower()
    return any(host == suf or host.endswith("." + suf) for suf in ALLOWED_HOST_SUFFIXES)

def _is_private_host(hostname: str) -> bool:
    try:
        # IPv4/IPv6 전체 확인
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            ip_obj = ipaddress.ip_address(ip)
            if (ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local
                    or ip_obj.is_reserved or ip_obj.is_multicast):
                return True
        return False
    except Exception:
        return True

@require_GET
@cache_page(60 * 60)
def proxy_image_view(request):
    raw = (request.GET.get("url") or "").strip()
    if not raw:
        return HttpResponseBadRequest("missing url")

    # 일부 클라이언트가 인코딩해 보내므로 디코드 후 파싱
    url = unquote(raw)
    try:
        p = urlparse(url)
        if p.scheme not in ALLOWED_SCHEMES or not p.hostname:
            return HttpResponseBadRequest("invalid url")

        if not _host_allowed(p.hostname):
            return HttpResponseBadRequest("host not allowed")

        if _is_private_host(p.hostname):
            return HttpResponseBadRequest("private host")

        if p.port not in (None, 80, 443):
            return HttpResponseBadRequest("port not allowed")
    except Exception:
        return HttpResponseBadRequest("bad url")

    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        "Referer": f"{p.scheme}://{p.hostname}/",
    }

    try:
        # 1) HEAD 시도 (일부 CDN은 차단) → 실패/허용 안 될 때 GET으로 폴백
        r_head = requests.head(url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        final_url = r_head.url if getattr(r_head, "url", None) else url
        pf = urlparse(final_url)

        # 리다이렉트된 경우도 최종 호스트가 허용 목록이어야만 통과
        if not _host_allowed(pf.hostname or "") or _is_private_host(pf.hostname or ""):
            return HttpResponseBadRequest("redirected to disallowed host")

        # 용량 체크(가능할 때만)
        cl = r_head.headers.get("Content-Length")
        if cl and cl.isdigit() and int(cl) > 5_000_000:
            return HttpResponseBadRequest("file too large")

        # 2) 본문 GET
        r = requests.get(final_url, headers=headers, stream=True,
                         timeout=REQUEST_TIMEOUT, allow_redirects=True)
    except Exception:
        return HttpResponseBadRequest("upstream fetch error")

    if not r.ok:
        return HttpResponse(f"upstream status {r.status_code}", status=r.status_code)

    ct = r.headers.get("Content-Type", "")
    if not ct.startswith("image/"):
        return HttpResponseBadRequest("not an image")

    resp = StreamingHttpResponse(r.iter_content(chunk_size=8192), content_type=ct)
    cl = r.headers.get("Content-Length")
    if cl and cl.isdigit():
        resp["Content-Length"] = cl
    resp["Cache-Control"] = "public, max-age=86400"
    return resp

def _abs_media_url(request, f) -> str:
    """ImageFieldFile → 절대 URL (없으면 빈 문자열)"""
    try:
        if not f:
            return ""
        url = f.url  # /media/...
        return request.build_absolute_uri(url)
    except Exception:
        return ""

MAX_REDIRECTS = 2

def _safe_get(url, headers, timeout, allow_redirects=False, original_host=None):
    """동일 호스트로의 짧은 리다이렉트만 허용"""
    if not allow_redirects:
        return requests.get(url, headers=headers, stream=True, timeout=timeout, allow_redirects=False)

    hops = 0
    cur = url
    while hops < MAX_REDIRECTS:
        r = requests.get(cur, headers=headers, stream=True, timeout=timeout, allow_redirects=False)
        if r.is_redirect and r.headers.get("Location"):
            nxt = urljoin(cur, r.headers["Location"])
            p = urlparse(nxt)
            if p.hostname != original_host:   # 다른 호스트로 튀면 차단
                return r  # 리다이렉트로 응답(4xx처럼 취급)
            cur = nxt
            hops += 1
            continue
        return r
    return r  # 최대 홉 도달 시 반환

# ─────────────────────────────────────────────────────────────
# Domain APIs
# ─────────────────────────────────────────────────────────────
class SearchHistoryViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet
):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SearchHistory.objects.filter(user=self.request.user).order_by('-id')

    def get_serializer_class(self):
        return (SearchHistoryCreateSerializer
                if self.action == 'create'
                else SearchHistorySerializer)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

# 동물 통계: 상위 4 + 기타 (별칭 사용)
def animal_stats(request):
    name_field = _animal_name_field(Report)  # 'animal__name_kor' | 'animal__name' | None

    if name_field:
        rows_qs = (
            Report.objects
            .values(animal_label=F(name_field))
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        full = [{'animal': (r['animal_label'] or '미상'), 'count': r['count']} for r in rows_qs]
    else:
        rows_qs = (
            Report.objects
            .values('animal_id')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        full = [{'animal': '미상', 'count': r['count']} for r in rows_qs]

    full.sort(key=lambda x: x['count'], reverse=True)

    etc_from_db = next((x for x in full if x['animal'] == '기타'), None)
    non_etc = [x for x in full if x['animal'] != '기타']

    top4 = non_etc[:4]
    rest = non_etc[4:]
    etc_sum = (etc_from_db['count'] if etc_from_db else 0) + sum(x['count'] for x in rest)

    data = top4 + ([{'animal': '기타', 'count': etc_sum}] if etc_sum > 0 else [])
    others_detail = sorted(rest, key=lambda x: x['count'], reverse=True)

    return JsonResponse({'data': data, 'others_detail': others_detail})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def animal_stats_raw(request):
    name_field = _animal_name_field(Report)

    if name_field:
        rows = (
            Report.objects
            .values(animal_label=F(name_field))
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        data = [{'animal': (r['animal_label'] or '미상'), 'count': r['count']} for r in rows]
    else:
        rows = (
            Report.objects
            .values('animal_id')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        data = [{'animal': '미상', 'count': r['count']} for r in rows]

    return Response(data)


def region_by_animal_stats(request):
    """
    Location × Animal 교차 통계. 동물명은 별칭으로 안전하게 반환.
    """
    base_field = _animal_name_field(Report)  # e.g. 'animal__name_kor'
    if base_field:
        after = base_field.split('__', 1)[1]  # 'name_kor' or 'name'
        animal_key = f"reports__animal__{after}"
        stats = (
            Location.objects
            .values('city', animal_label=F(animal_key))
            .annotate(count=Count('reports__id'))
            .order_by('city')
        )
        result = [
            {"city": r["city"], "animal": (r["animal_label"] or "미상"), "count": r["count"]}
            for r in stats
        ]
    else:
        stats = (
            Location.objects
            .values('city')
            .annotate(count=Count('reports__id'))
            .order_by('city')
        )
        result = [
            {"city": r["city"], "animal": "미상", "count": r["count"]}
            for r in stats
        ]

    return JsonResponse(result, safe=False)


class AnimalViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Animal.objects.all()
    serializer_class = AnimalSerializer
    permission_classes = [AllowAny]

    @action(detail=False, url_path='search', permission_classes=[AllowAny])
    def search(self, request):
        q = request.query_params.get('q', '').strip()
        if not q:
            return Response([], status=status.HTTP_200_OK)
        qs = Animal.objects.filter(Q(name_kor__icontains=q) | Q(name_eng__icontains=q))
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)


class LocationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        Location.objects
        .prefetch_related('reports', 'reports__user')
        .all()
    )
    serializer_class = LocationSerializer
    permission_classes = [AllowAny]

    filter_backends = [DjangoFilterBackend, OrderingFilter, SearchFilter]
    filterset_fields = ['reports__id', 'reports__user_id', 'city', 'district', 'region']
    search_fields = ['region', 'address', 'city', 'district']
    ordering_fields = ['id', 'latitude', 'longitude']
    ordering = ['-id']


class SavedPlaceViewSet(viewsets.ModelViewSet):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        u = self.request.user
        base = SavedPlace.objects.select_related('location')
        return base if u.is_superuser else base.filter(user=u)

    def get_serializer_class(self):
        return SavedPlaceCreateSerializer if self.action == 'create' else SavedPlaceReadSerializer

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class AppBannerViewSet(viewsets.ModelViewSet):
    queryset = AppBanner.objects.all()
    authentication_classes = [JWTAuthentication]
    # 대시보드에서만 작성/수정 → 관리자만
    permission_classes = [IsAdminUser]
    serializer_class = AppBannerSerializer

    # 생성 시 FCM 데이터푸시로 즉시 노출 트리거(선택)
    def perform_create(self, serializer):
        obj = serializer.save()
        try:
            # 기존 브로드캐스트 유틸 재사용
            send_push_only(
                title="공지",
                body=obj.text,
                data={"kind":"banner","banner_id":str(obj.id),"text":obj.text,"cta_url":obj.cta_url or ""},
                user_ids=None,  # 전체
            )
        except Exception as e:
            # 실패해도 API 자체는 성공
            print("[FCM] banner push failed:", e)

# 활성 배너 조회(앱에서 사용, 인증 불필요)
class AppBannerActiveList(APIView):
    authentication_classes = []                      # 인증 완전 비활성화
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        now = timezone.now()
        qs = (AppBanner.objects
              .filter(is_active=True)
              .filter(Q(starts_at__isnull=True) | Q(starts_at__lte=now))
              .filter(Q(ends_at__isnull=True) | Q(ends_at__gte=now))
              .order_by('-priority', '-id'))
        top = qs.first()
        return Response({"data": AppBannerReadSerializer(top).data if top else None})

class ReportViewSet(mixins.ListModelMixin,
                    mixins.CreateModelMixin,
                    mixins.RetrieveModelMixin,
                    mixins.UpdateModelMixin,
                    mixins.DestroyModelMixin,
                    viewsets.GenericViewSet):
    """
    신고 CRUD
    - 일반 사용자: 본인 신고만
    - 관리자/스태프: 전체
    """
    queryset = Report.objects.select_related('animal', 'user', 'location').all()
    serializer_class = ReportSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    # ✅ 파일 업로드를 위해 parser_classes 정확히 지정
    parser_classes = [MultiPartParser, FormParser]

    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = ReportFilter
    ordering_fields = ['report_date']
    ordering = ['-report_date']

    @action(detail=False, methods=['get'], url_path='summary')
    def summary(self, request):
        print('[summary] Authorization =', request.META.get('HTTP_AUTHORIZATION', ''))

    def get_queryset(self):
        user = self.request.user
        qs = Report.objects.select_related('animal', 'user', 'location')
        # ✅ staff/superuser는 전체, 그 외는 본인 것만
        if getattr(user, 'is_superuser', False) or getattr(user, 'is_staff', False):
            return qs
        return qs.filter(user=user)

    def get_permissions(self):
        # ✅ 생성 허용 여부를 settings.ALLOW_ANON_REPORTS 로 토글
        from django.conf import settings
        allow_anon = getattr(settings, 'ALLOW_ANON_REPORTS', True)
        if self.action == 'create':
            return [AllowAny()] if allow_anon else [IsAuthenticated()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == 'create':
            return ReportCreateSerializer
        return ReportSerializer

    def perform_create(self, serializer):
        """
        - 로그인 사용자는 Report.user에 연결
        - 익명 허용일 때는 user=None 으로 저장
        - 요청에 reporter_name 유사 필드가 오면 모델에 존재하는 경우에 한해 함께 저장
        """
        u = getattr(self.request, 'user', None)
        data = self.request.data or {}
        extra = {}

        # 모델에 해당 필드가 실제로 있을 때만 반영되도록 방어적으로 처리
        model_field_names = {f.name for f in Report._meta.get_fields()}
        for k in ("reporter_name", "reporter", "contact_name", "writer_name"):
            if k in data and k in model_field_names:
                v = data.get(k)
                if isinstance(v, str) and v.strip():
                    extra[k] = v.strip()

        if u and getattr(u, 'is_authenticated', False):
            serializer.save(user=u, **extra)  # 로그인 사용자는 소유자 연결
        else:
            serializer.save(**extra)          # 익명 신고(허용된 경우)

    def perform_update(self, serializer):
        # 상태 변경 시 알림 생성 로직 유지
        instance: Report = self.get_object()
        old_status = instance.status
        with transaction.atomic():
            report: Report = serializer.save()
            new_status = report.status

            if old_status != new_status:
                admin_obj = getattr(self.request.user, "admin", None) if is_admin(self.request.user) else None
                _upsert_notification_for_report(
                    report=report,
                    reply=None,
                    status_change=f"{old_status}->{new_status}",
                    admin_obj=admin_obj,
                )

    def list(self, request, *args, **kwargs):
        """
        /api/reports/?from=YYYY-MM-DD&to=YYYY-MM-DD
        날짜 필터는 report_date 필드 타입(Date vs DateTime)에 맞춰 적용
        """
        queryset = self.filter_queryset(self.get_queryset())

        from_date = request.query_params.get("from")
        to_date   = request.query_params.get("to")

        if from_date and to_date:
            try:
                start = datetime.strptime(from_date, "%Y-%m-%d").date()
                end   = datetime.strptime(to_date,   "%Y-%m-%d").date()
                field = Report._meta.get_field('report_date')
                if isinstance(field, DateTimeField):
                    queryset = queryset.filter(
                        report_date__date__gte=start,
                        report_date__date__lte=end
                    )
                else:
                    queryset = queryset.filter(
                        report_date__gte=start,
                        report_date__lte=end
                    )
            except ValueError:
                pass

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    # ===== 기존 요약 통계 (별칭 사용) =====
    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        qs = self.filter_queryset(self.get_queryset())
        total = qs.count()

        name_field = _animal_name_field(Report)
        if name_field:
            by_animal_rows = qs.values(animal_label=F(name_field)).annotate(c=Count('id'))
            by_animal = {(r['animal_label'] or '미상'): r['c'] for r in by_animal_rows}
        else:
            by_animal = {'미상': total} if total else {}

        by_status = dict(qs.values_list('status').annotate(c=Count('id')))

        lqs = Location.objects.filter(id__in=qs.values('location_id'))
        area_expr = Case(
            When(~Q(district__isnull=True) & ~Q(district='') & ~Q(district='-'), then=F('district')),
            When(~Q(city__isnull=True)     & ~Q(city='')     & ~Q(city='-'),     then=F('city')),
            default=Value('미상'),
            output_field=CharField(),
        )
        rows = (
            lqs.annotate(area=area_expr)
               .values('area')
               .annotate(c=Count('id'))
               .order_by('-c')
        )
        by_region = {r['area']: r['c'] for r in rows}

        return Response({
            'total': total,
            'by_status': by_status,
            'by_animal': by_animal,
            'by_region': by_region,
        })

    # ===== 동물별 신고 건수 (도넛) - 별칭 사용 =====
    @action(detail=False, methods=['get'], url_path='stats/animal')
    def stats_animal(self, request):
        qs = self.filter_queryset(self.get_queryset())
        name_field = _animal_name_field(Report)

        if name_field:
            rows = (
                qs.values(animal_label=F(name_field))
                  .annotate(count=Count('id'))
                  .order_by('-count')
            )
            rows_list = [{'animal': (r['animal_label'] or '미상'), 'count': r['count']} for r in rows]
        else:
            rows = (
                qs.values('animal_id')
                  .annotate(count=Count('id'))
                  .order_by('-count')
            )
            rows_list = [{'animal': '미상', 'count': r['count']} for r in rows]

        rows_list.sort(key=lambda x: x['count'], reverse=True)
        top4 = rows_list[:4]
        top_animals = [x['animal'] for x in top4]

        etc_count = sum(x['count'] for x in rows_list[4:])
        data = top4 + ([{'animal': '기타', 'count': etc_count}] if etc_count > 0 else [])
        return Response({"top_animals": top_animals, "data": data})

    # ===== 지역 × 동물별 신고 건수 (스택 바) - 별칭 사용 =====
    @action(detail=False, methods=['get'], url_path='stats/region-by-animal')
    def stats_region_by_animal(self, request):
        """
        GET /api/reports/stats/region-by-animal
        응답: [{ "city": "서울", "animal": "고라니", "count": 10 }, ...]
        """
        qs  = self.filter_queryset(self.get_queryset())
        lqs = Location.objects.filter(id__in=qs.values('location_id'))

        base_field = _animal_name_field(Report)
        if base_field:
            after = base_field.split('__', 1)[1]
            animal_field = f"reports__animal__{after}"
            rows = (
                lqs.values('city', animal_label=F(animal_field))
                   .annotate(count=Count('reports__id'))
                   .order_by('city', '-count')
            )
            norm_rows = [{
                "city": (r['city'] or '미상'),
                "animal": (r['animal_label'] or '미상'),
                "count": r['count']
            } for r in rows]
        else:
            rows = (
                lqs.values('city')
                   .annotate(count=Count('reports__id'))
                   .order_by('city', '-count')
            )
            norm_rows = [{
                "city": (r['city'] or '미상'),
                "animal": '미상',
                "count": r['count']
            } for r in rows]

        # 상위 4개 도시 + 기타 합치기
        city_totals = {}
        for r in norm_rows:
            c = r['city']
            city_totals[c] = city_totals.get(c, 0) + r['count']
        top4_names = [name for name, _cnt in sorted(city_totals.items(), key=lambda x: x[1], reverse=True)[:4]]

        data = []
        etc_city_animals = {}
        cities = sorted(set(r['city'] for r in norm_rows))
        for city in cities:
            city_rows = [r for r in norm_rows if r['city'] == city]
            animal_counts = {}
            for r in city_rows:
                a = r['animal']
                animal_counts[a] = animal_counts.get(a, 0) + r['count']

            sorted_animals = sorted(animal_counts.items(), key=lambda x: x[1], reverse=True)
            top4_animals   = sorted_animals[:4]
            other_animals  = sorted_animals[4:]
            etc_animal_cnt = sum(v for _, v in other_animals)

            final_animals = top4_animals[:]
            if etc_animal_cnt > 0:
                final_animals.append(("기타", etc_animal_cnt))

            if city in top4_names:
                for animal, cnt in final_animals:
                    data.append({"city": city, "animal": animal, "count": cnt})
            else:
                for animal, cnt in final_animals:
                    etc_city_animals[animal] = etc_city_animals.get(animal, 0) + cnt

        for animal, cnt in etc_city_animals.items():
            data.append({"city": "기타", "animal": animal, "count": cnt})

        return Response(data)

    @action(
        detail=False,
        methods=["get"],
        url_path="my-points",
        permission_classes=[IsAuthenticated],   # JWT로 인증 필요
    )
    def my_points(self, request):
        """
        GET /api/reports/my-points/
        내 신고 중 좌표가 있는 것만 포인트로 반환
        응답: {"points":[{id, lat, lng, animal, status, date, address}]}
        """
        # 내 신고만
        qs = (Report.objects
              .filter(user=request.user)
              .select_related("location", "animal"))

        items = []
        for r in qs:
            # 좌표 얻기: 위치 FK가 있으면 거기서, 아니면 Report 자체의 lat/lng 사용(있다면)
            lat = None
            lng = None
            addr = ""

            if getattr(r, "location", None):
                loc = r.location
                lat = getattr(loc, "latitude", None) or getattr(loc, "lat", None)
                lng = getattr(loc, "longitude", None) or getattr(loc, "lng", None)
                # 주소/지역 후보 중 있는 값 하나 고르기
                for f in ("address", "region", "district", "city", "name", "detail", "road_address"):
                    v = getattr(loc, f, None)
                    if v:
                        addr = v
                        break
            else:
                # 위치 FK가 없다면 모델에 lat/lng가 직접 있는 경우 지원
                lat = getattr(r, "latitude", None)
                lng = getattr(r, "longitude", None)
                for f in ("address", "report_region", "region"):
                    v = getattr(r, f, None)
                    if v:
                        addr = v
                        break

            if lat is None or lng is None:
                continue  # 좌표 없으면 스킵

            # 동물명(별칭 안전 처리)
            animal = None
            if getattr(r, "animal", None):
                animal = getattr(r.animal, "name_kor", None) or getattr(r.animal, "name", None)
            if not animal:
                animal = getattr(r, "animal_name", None) or "미상"

            # 날짜(Report에 따라 Date/DateTime)
            dt = getattr(r, "report_date", None) or getattr(r, "created_at", None)
            date_iso = dt.isoformat() if dt else None

            items.append({
                "id": r.id,
                "lat": float(lat),
                "lng": float(lng),
                "animal": animal,
                "status": getattr(r, "status", "") or "",
                "date": date_iso,
                "address": addr or "",
            })

        return Response({"points": items})

    # ===== 홈 카드용 요약 =====
    @action(detail=False, methods=['get'], url_path='summary')
    def summary(self, request):
        """
        GET /api/reports/summary/?scope=global|me&period=all|7d|30d
        """
        scope  = (request.query_params.get('scope') or 'global').lower()
        period = (request.query_params.get('period') or 'all').lower()

        base = Report.objects.select_related('animal').all()
        if scope == 'me':
            base = base.filter(user=request.user)

        now = timezone.now()
        if period == '7d':
            start = now - timezone.timedelta(days=7)
        elif period == '30d':
            start = now - timezone.timedelta(days=30)
        else:
            start = None

        if start is not None:
            field = Report._meta.get_field('report_date')
            if isinstance(field, DateTimeField):
                base = base.filter(report_date__gte=start)
            else:
                base = base.filter(report_date__gte=start.date())

        total_reports = base.count()
        last_dt = base.aggregate(last=Max('report_date'))['last']

        name_field = _animal_name_field(base.model)  # 'animal__name_kor' | 'animal__name' | None

        if name_field:
            top_row = (
                base.values('animal_id', animal_label=F(name_field))
                    .annotate(cnt=Count('id'))
                    .order_by('-cnt')
                    .first()
            )
            top_animal = None
            if top_row:
                top_animal = {
                    "id":   top_row['animal_id'],
                    "name": top_row['animal_label'] or '미상',
                    "count": top_row['cnt'],
                }
        else:
            top_row = (
                base.values('animal_id')
                    .annotate(cnt=Count('id'))
                    .order_by('-cnt')
                    .first()
            )
            top_animal = None
            if top_row:
                top_animal = {
                    "id":   top_row['animal_id'],
                    "name": '미상',
                    "count": top_row['cnt'],
                }

        return Response({
            "total_reports": total_reports,
            "top_animal": top_animal,
            "last_report_date": last_dt.isoformat() if last_dt else None,
        })

# ---------- Kakao 역지오 ----------
class ReverseGeocodeView(APIView):
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]

    def post(self, request: Request):
        lat = request.data.get('lat')
        lng = request.data.get('lng')
        if lat is None or lng is None:
            return Response({'detail': 'lat,lng 필수'}, status=400)

        try:
            url = "https://dapi.kakao.com/v2/local/geo/coord2address.json"
            r = requests.get(
                url,
                params={'x': lng, 'y': lat},
                headers={'Authorization': f'KakaoAK {settings.KAKAO_REST_API_KEY}'},
                timeout=8,
            )
            if not r.ok:
                return Response({'detail': f'kakao {r.status_code}'}, status=502)
            data = r.json()
            addr = None
            if data.get('documents'):
                ad = data['documents'][0].get('address') or data['documents'][0].get('road_address')
                if ad:
                    addr = ad.get('address_name')
            if not addr:
                addr = f"{float(lat):.5f}, {float(lng):.5f}"
            return Response({'address': addr})
        except Exception as e:
            return Response({'detail': str(e)}, status=502)

# ---------- AI 인식(더미) ----------
class RecognizeAnimalView(APIView):
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser]

    MAX_UPLOAD = 12_000_000  # 5MB

    _ALIAS_EN = {
        "goat": "goat", "roe deer": "roe deer",
        "great egret": "egret", "intermediate egret": "egret", "little egret": "egret", "egret": "egret",
        "grey heron": "heron", "gray heron": "heron", "heron": "heron",
        "hare": "hare",
        "korean squirrel": "squirrel", "eurasian red squirrel": "squirrel", "squirrel": "squirrel",
        "chipmunk": "chipmunk", "wild boar": "wild boar", "raccoon": "raccoon",
        "asiatic black bear": "asiatic black bear", "weasel": "weasel", "dog": "dog", "cat": "cat",
    }

    _ALIAS_KO = {
        "goat": "고라니", "roe deer": "노루", "egret": "중대백로", "heron": "왜가리",
        "squirrel": "다람쥐", "chipmunk": "청설모", "wild boar": "멧돼지", "weasel": "족제비",
        "dog": "강아지", "cat": "고양이", "raccoon": "너구리", "asiatic black bear": "반달가슴곰",
        "hare": "멧토끼",
    }

    _GROUP_LABEL_KO = {
        "deer": "고라니/노루",
        "heron_egret": "중대백로/왜가리",
        "sciuridae": "다람쥐/청설모",
    }
    # rep_eng -> group 코드 강제 매핑
    _ENG_TO_GROUP = {
        "goat": "deer",
        "roe deer": "deer",
        "egret": "heron_egret",
        "heron": "heron_egret",
        "squirrel": "sciuridae",
        "chipmunk": "sciuridae",
    }

    @classmethod
    def _norm_eng(cls, label_en: str) -> str:
        k = (label_en or "").strip().lower()
        return cls._ALIAS_EN.get(k, k)

    @classmethod
    def _to_kor(cls, db_key_en: str) -> Optional[str]:
        return cls._ALIAS_KO.get(db_key_en)

    def _find_animal(self, rep_eng: str, display_ko: Optional[str]):
        qs = Animal.objects.all()
        q = Q(name_eng__iexact=rep_eng)
        if display_ko:
            q |= Q(name_kor__iexact=display_ko)
        return qs.filter(q).order_by("id").first()

    def post(self, request: Request):
        f = request.FILES.get("photo") or request.FILES.get("image")
        if not f:
            return Response({"detail": "photo(또는 image) 파일이 필요합니다."}, status=400)

        # 1) 크기 제한
        if getattr(f, "size", 0) > self.MAX_UPLOAD:
            return Response({"detail": "file too large"}, status=413)

        # 2) 포맷 검증 + EXIF 회전 보정 + RGB 변환
        try:
            img = Image.open(f)
            img.load()
            try:
                from PIL import ImageOps
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass
            if img.mode != "RGB":
                img = img.convert("RGB")
        except Exception:
            return Response({"detail": "invalid image"}, status=400)

        grouped = (request.query_params.get("grouped") in ("1", "true", "yes"))

        if grouped:
            topg = predict_topk_grouped(img, k=3)
            results = []
            for g in topg:
                members = g.get("members") or []           # 예: [("Goat", 0.99), ("Roe deer", 0.01)]
                top_member_en = members[0][0] if members else ""
                rep_eng = self._norm_eng(top_member_en)    # "goat" 등

                # ✅ group 코드 정규화: 모델이 goat/heron 등으로 주더라도 의도한 그룹으로 강제
                group_code = self._ENG_TO_GROUP.get(rep_eng, (g.get("group") or ""))

                # ✅ 그룹 KO 라벨 우선 적용
                display_ko = self._GROUP_LABEL_KO.get(group_code)

                # 그룹 라벨이 없으면 멤버 KO를 합성(A/B)
                if not display_ko:
                    mapped = []
                    for m, _p in members:
                        key = self._norm_eng(m)
                        mapped.append(self._to_kor(key) or m)
                    mapped = list(dict.fromkeys(mapped))  # 중복 제거
                    display_ko = "/".join(mapped) if mapped else (self._to_kor(rep_eng) or top_member_en)

                # 보고서 저장용 animal_id는 탑 멤버 기준으로 매핑
                a = self._find_animal(rep_eng, display_ko)

                results.append({
                    "group": group_code,          # 예: "deer"
                    "label": display_ko,          # 예: "고라니/노루"
                    "label_ko": display_ko,
                    "prob": g.get("prob"),
                    "members": members,           # 원본 멤버 그대로
                    "rep_eng": rep_eng,           # 탑 멤버 EN
                    "animal_id": a.id if a else None,
                })

            return Response({"mode": "grouped", "results": results})

        topk = predict_topk(img, k=3)
        best = topk[0]
        rep_eng = self._norm_eng(best["label"])
        label_ko = self._to_kor(rep_eng)
        a = self._find_animal(rep_eng, label_ko)

        return Response({
            "mode": "single",
            "label": best["label"],
            "label_norm": rep_eng,
            "label_ko": label_ko,
            "prob": best["prob"],
            "animal_id": a.id if a else None,
            "topk": topk,
        })
def _norm_text(s: str) -> str:
    return (s or '').strip().lower()

@require_GET
@permission_classes([AllowAny])
def animal_resolve(request):
    """
    GET /api/animals/resolve/?q=<label>
    반환: { "animal_id": <int>, "confidence": "exact|alias|startswith|contains|fallback", "matched": "<str>" }
    """
    label = _norm_text(request.GET.get('q', ''))
    FALLBACK_UNKNOWN_ID = 31

    if not label:
        return JsonResponse({"animal_id": FALLBACK_UNKNOWN_ID, "confidence": "fallback", "matched": ""})

    # 프로젝트 실데이터 기준: name_kor / name_eng 필드 사용
    alias_map = {
        # EN → KO 대표명(필요시 확장)
        "goat": "고라니",
        "roe deer": "노루",
        "wild boar": "멧돼지",
        "raccoon": "너구리",
        "chipmunk": "청설모",
        "squirrel": "다람쥐",
        "asiatic black bear": "반달가슴곰",
        "hare": "멧토끼",
        "weasel": "족제비",
        "heron": "왜가리",
        "egret": "중대백로",
        "dog": "개",
        "cat": "고양이",
    }

    candidates = [label]
    if label in alias_map:
        candidates.append(_norm_text(alias_map[label]))

    def query_any(terms, lookups):
        qs = Animal.objects.all()
        for term in terms:
            q = Q()
            for lk in lookups:
                q |= Q(**{lk: term})
            obj = qs.filter(q).first()
            if obj:
                return obj, term
        return None, None

    # 우선순위: exact → alias-exact → startswith → contains
    exact_lookups = ["name_kor__iexact", "name_eng__iexact"]
    starts_lookups = ["name_kor__istartswith", "name_eng__istartswith"]
    contains_lookups = ["name_kor__icontains", "name_eng__icontains"]

    obj, matched = query_any([candidates[0]], exact_lookups)
    if obj:
        return JsonResponse({"animal_id": obj.id, "confidence": "exact", "matched": matched})

    if len(candidates) > 1:
        obj, matched = query_any([candidates[1]], exact_lookups)
        if obj:
            return JsonResponse({"animal_id": obj.id, "confidence": "alias", "matched": matched})

    obj, matched = query_any(candidates, starts_lookups)
    if obj:
        return JsonResponse({"animal_id": obj.id, "confidence": "startswith", "matched": matched})

    obj, matched = query_any(candidates, contains_lookups)
    if obj:
        return JsonResponse({"animal_id": obj.id, "confidence": "contains", "matched": matched})

    return JsonResponse({"animal_id": FALLBACK_UNKNOWN_ID, "confidence": "fallback", "matched": ""})

# ---------- 무인증 신고 ----------
class ReportNoAuthView(APIView):
    """
    multipart: photo, animalId, [locationId | lat,lng], status
    """
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request: Request):
        ser = ReportNoAuthCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        rpt = ser.save()
        return Response({
            'report_id': rpt.id,
            'status': rpt.status,
            'animal': getattr(rpt.animal, 'name_kor', None),
            'created_at': rpt.report_date,
        }, status=201)

def _report_to_dict(request, rpt: Report):
    """
    대시보드 리스트용 표시 데이터 생성:
    - 동물명: Animal.name_kor → name → name_eng → Report.animal_name/label → '미상'
    - 신고자: user.username → user.email → ''
    - 지역: Location.address → region → district → city → name → detail → road_address
           (없으면 Report.report_region → region → address)
    - 일시: report_date(또는 created_at/created/date) → 'YYYY-MM-DD HH:MM'
    - created_at 키를 유지(프론트 호환). 필요 시 report_date 문자열도 함께 반환.
    """
    # 1) 동물명
    animal_name = ""
    a = getattr(rpt, "animal", None)
    if a:
        for f in ("name_kor", "name", "name_eng", "label", "species"):
            v = getattr(a, f, None)
            if isinstance(v, str) and v.strip():
                animal_name = v.strip()
                break
    if not animal_name:
        for f in ("animal_name", "animal_label", "animal"):
            v = getattr(rpt, f, None)
            if isinstance(v, str) and v.strip():
                animal_name = v.strip()
                break
    if not animal_name:
        animal_name = "미상"

    # 2) 신고자
    reporter_name = ""
    u = getattr(rpt, "user", None)
    if u:
        for f in ("username", "email", "nickname"):
            v = getattr(u, f, None)
            if isinstance(v, str) and v.strip():
                reporter_name = v.strip()
                break

    # 3) 지역
    region = ""
    loc = getattr(rpt, "location", None)
    if loc:
        for f in ("address", "region", "district", "city", "name", "detail", "road_address"):
            v = getattr(loc, f, None)
            if isinstance(v, str) and v.strip():
                region = v.strip()
                break
    if not region:
        for f in ("report_region", "region", "address"):
            v = getattr(rpt, f, None)
            if isinstance(v, str) and v.strip():
                region = v.strip()
                break

    # 4) 일시(문자열)
    dt = (
        getattr(rpt, "report_date", None)
        or getattr(rpt, "created_at", None)
        or getattr(rpt, "created", None)
        or getattr(rpt, "date", None)
    )
    created_str = ""
    if dt:
        try:
            # DateTime → 로컬타임 변환 후 포맷 / Date → 자정 시각으로 포맷
            if isinstance(dt, datetime):
                created_str = timezone.localtime(dt).strftime("%Y-%m-%d %H:%M")
            elif isinstance(dt, date):
                created_str = datetime(dt.year, dt.month, dt.day).strftime("%Y-%m-%d 00:00")
            else:
                created_str = str(dt)
        except Exception:
            created_str = str(dt)

    return {
        "id": rpt.id,
        "animal": animal_name,
        "reporter": reporter_name or "",
        "region": region or "",
        "status": getattr(rpt, "status", "") or "",
        # ✅ 프론트 호환을 위해 created_at 키 유지
        "created_at": created_str,
        # 선택: 필요하면 프론트 마이그레이션 중에 참고하도록 동일 값 제공
        "report_date": created_str,
        "image_url": _build_image_url(request, rpt),
    }

@login_required
@user_passes_test(_is_staff)
def dashboard_reports(request):
    """
    GET /api/dashboard/reports/?page=1&page_size=20&q=키워드
    - 결과: { page, total_pages, results:[{id,animal,reporter,region,status,created_at,image_url}] }
    - 세션 로그인(스태프) 필요
    """
    page = int(request.GET.get('page') or 1)
    page_size = int(request.GET.get('page_size') or 20)
    status_q = (request.GET.get('status') or '').strip()

    qs = Report.objects.select_related('animal', 'user', 'location').all().order_by('-id')

    if status_q:
        qs = qs.filter(status=status_q)

    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(page)

    data = {
        "page": page_obj.number,
        "total_pages": paginator.num_pages,
        "results": [_report_to_dict(request, rpt) for rpt in page_obj.object_list],
    }
    return JsonResponse(data, status=200)

@login_required
@user_passes_test(_is_staff)
def dashboard_report_stats(request):
    """
    GET /api/dashboard/report-stats/
    - 총 신고 수, 오늘 접수, 미해결
    """
    total = Report.objects.count()
    today = Report.objects.filter(
        # created_at/created/ date 필드명에 맞춰 수정
        report_date=timezone.localdate()
    ).count() if hasattr(Report, 'report_date') else 0

    unresolved = Report.objects.exclude(status='completed').count()
    return JsonResponse({
        "total": total,
        "today": today,
        "unresolved": unresolved,
    }, status=200)

@login_required
@user_passes_test(_is_staff)
def dashboard_reporters(request):
    """
    GET /api/dashboard/reporters/?limit=10
    - 신고 상위 사용자 Top N
    - 결과: { results:[{ name, count }] }
    """
    try:
        limit = int(request.GET.get('limit') or 10)
    except Exception:
        limit = 10

    qs = (Report.objects
          .values('user__username', 'user__email')
          .annotate(count=Count('id'))
          .order_by('-count')[:limit])

    results = []
    for row in qs:
        name = row.get('user__username') or row.get('user__email') or '(알수없음)'
        results.append({"name": name, "count": row['count']})

    return JsonResponse({"results": results}, status=200)

# ─────────────────────────────────────────────────────────────
# Notification
# ─────────────────────────────────────────────────────────────
class NotificationViewSet(mixins.ListModelMixin,
                          mixins.CreateModelMixin,
                          mixins.RetrieveModelMixin,
                          mixins.UpdateModelMixin,
                          mixins.DestroyModelMixin,
                          viewsets.GenericViewSet):
    queryset = (Notification.objects
                .select_related('user', 'admin', 'report', 'report__animal', 'report__user')
                .all())
    serializer_class = NotificationSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAdminOrReadGroup]
    pagination_class = DefaultPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = NotificationFilter
    ordering_fields = ['id', 'created_at']
    ordering = ['-created_at', '-id']

    def get_queryset(self):
        qs = (Notification.objects
              .select_related('user', 'admin', 'report', 'report__animal', 'report__user'))

        # ✅ 상세 조회는 type 필터 없이 전체에서 검색
        if getattr(self, 'action', None) == 'retrieve':
            return qs.order_by('-created_at', '-id')

        qtype = (self.request.query_params.get('type') or '').strip().lower()
        user  = self.request.user

        if qtype == 'group':
            return qs.filter(type='group').order_by('-created_at', '-id')

        if qtype == 'individual':
            if not (user and user.is_authenticated):
                return qs.none()
            if is_admin(user):
                scope = (self.request.query_params.get('scope') or '').strip().lower()
                base = qs.filter(type='individual')
                if scope in ('mine', 'me', 'my'):
                    base = base.filter(Q(user_id=user.id) | Q(admin__user_id=user.id))
                return base.order_by('-created_at', '-id')
            return qs.filter(type='individual', user_id=user.id).order_by('-created_at', '-id')

        # 목록에는 type이 꼭 필요 (list에서 400 처리)
        return qs.none()

    def list(self, request, *args, **kwargs):
        qtype = (request.query_params.get('type') or '').strip().lower()
        if qtype not in ('group', 'individual'):
            return Response(
                {'detail': "type=group 또는 type=individual 파라미터가 필요합니다."},
                status=status.HTTP_400_BAD_REQUEST
            )
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        if not is_admin(self.request.user):
            raise PermissionDenied("관리자만 생성할 수 있습니다.")

        t = serializer.validated_data.get('type')
        target_user = serializer.validated_data.get('user')
        if t == 'individual' and target_user and getattr(target_user, 'admin', None):
            raise ValidationError('관리자 계정은 개인 알림 수신자가 될 수 없습니다.')

        admin_obj = getattr(self.request.user, 'admin', None)
        serializer.save(admin=admin_obj)

    def perform_update(self, serializer):
        if not is_admin(self.request.user):
            raise PermissionDenied("관리자만 수정할 수 있습니다.")

        t = serializer.validated_data.get('type', getattr(serializer.instance, 'type', None))
        target_user = serializer.validated_data.get('user', getattr(serializer.instance, 'user', None))
        if t == 'individual' and target_user and getattr(target_user, 'admin', None):
            raise ValidationError('관리자 계정은 개인 알림 수신자가 될 수 없습니다.')

        admin_obj = getattr(self.request.user, 'admin', None)
        serializer.save(admin=admin_obj)

    @action(detail=False, methods=['post'], url_path='send-group', permission_classes=[IsAdminUser])
    def send_group(self, request):
        """
        body:
        {
          "user_ids": [12, 34],   # 없으면 전체 공지
          "status_change": "checking->completed",
          "reply": "공지 내용"
        }
        """
        user_ids = request.data.get('user_ids') or []
        status_change = request.data.get('status_change')
        reply = request.data.get('reply')

        if not status_change and not reply:
            return Response({'detail': 'status_change 또는 reply 중 하나는 필요합니다.'},
                            status=status.HTTP_400_BAD_REQUEST)

        if status_change and status_change not in dict(Notification.STATUS_CHANGE_CHOICES):
            return Response({'status_change': f'허용되지 않은 값입니다: {status_change}'},
                            status=status.HTTP_400_BAD_REQUEST)

        admin_obj = getattr(request.user, 'admin', None) if is_admin(request.user) else None

        if not user_ids:
            Notification.objects.create(
                type='group', user=None,
                status_change=status_change, reply=reply,
                admin=admin_obj
            )
            return Response({'created': 1}, status=status.HTTP_201_CREATED)

        UserModel = get_user_model()
        users = UserModel.objects.filter(id__in=user_ids, admin__isnull=True)  # 관리자 제외
        to_create = [
            Notification(
                type='individual', user=u,
                status_change=status_change, reply=reply,
                admin=admin_obj
            ) for u in users
        ]
        Notification.objects.bulk_create(to_create)
        return Response({'created': len(to_create)}, status=status.HTTP_201_CREATED)

class FeedbackViewSet(viewsets.ModelViewSet):
    queryset = Feedback.objects.select_related('report', 'user', 'admin').all()
    serializer_class = FeedbackSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['report', 'user', 'admin']
    ordering_fields = ['feedback_datetime', 'feedback_id']
    ordering = ['-feedback_datetime']

    def get_queryset(self):
        qs = super().get_queryset()
        u = self.request.user

        if not is_admin(u):
            qs = qs.filter(user_id=u.id)
        else:
            scope = (self.request.query_params.get('scope') or '').lower()
            if scope in ('mine', 'me', 'my'):
                qs = qs.filter(Q(user_id=u.id) | Q(admin__user_id=u.id))

        role = (self.request.query_params.get('role') or '').lower()
        if role == 'reporter':
            qs = qs.filter(user_id=u.id)
        elif role == 'admin':
            qs = qs.filter(admin__user_id=u.id)

        return qs.order_by('-feedback_datetime', '-feedback_id')

    def perform_create(self, serializer):
        with transaction.atomic():
            fb: Feedback = serializer.save()
            rpt: Report = fb.report
            admin_obj = _resolve_admin_from_request_or_feedback(self.request, fb)

            _upsert_notification_for_report(
                report=rpt,
                reply=(fb.content or ""),
                status_change=None,
                admin_obj=admin_obj,
            )

def my_notifications_qs(request):
    return (Feedback.objects
            .filter(Q(user_id=request.user.id) | Q(admin__user_id=request.user.id))
            .order_by('-feedback_datetime', '-feedback_id'))

class StatisticViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Statistic.objects.all().order_by('-state_year', '-state_month')
    serializer_class = StatisticSerializer
    permission_classes = [IsAuthenticated]

@api_view(['GET'])
@permission_classes([AllowAny])
def animal_info(request):
    name = request.GET.get('name')
    a = Animal.objects.filter(name_kor=name).order_by('id').first()
    if not a:
        return Response({"message": "해당 동물 정보가 없습니다."}, status=404)

    if request.user and request.user.is_authenticated:
        SearchHistory.objects.create(user=request.user, keyword=name)

    feats = getattr(a, "features", None)
    if isinstance(feats, list):
        features = feats
    elif isinstance(feats, str) and feats.strip():
        features = [s.lstrip('- ').strip() for s in feats.splitlines() if s.strip()]
    else:
        features = []

    proxied = None
    if getattr(a, "image_url", None):
        q = urlencode({'url': a.image_url})
        proxied = request.build_absolute_uri(f"/api/image-proxy/?{q}")

    return Response({
        "name":        a.name_kor,
        "english":     getattr(a, "name_eng", None),
        "image_url":   getattr(a, "image_url", None),
        "image":       getattr(a, "image_url", None),
        "imageUrl":    getattr(a, "image_url", None),
        "proxied_image_url": proxied,
        "features":    features,
        "precautions": getattr(a, "precautions", None),
        "description": getattr(a, "description", None),
    })

class AdminViewSet(mixins.ListModelMixin,
                   mixins.CreateModelMixin,
                   mixins.RetrieveModelMixin,
                   mixins.UpdateModelMixin,
                   mixins.DestroyModelMixin,
                   viewsets.GenericViewSet):
    queryset = Admin.objects.all()
    serializer_class = AdminSerializer
    permission_classes = [IsAdminUser]

class MeProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        serializer = ProfileSerializer(profile)
        return Response(serializer.data)

    def put(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        serializer = ProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        current_password = request.data.get('current_password') or ''
        new_password = request.data.get('new_password') or ''

        if not request.user.check_password(current_password):
            return Response({'detail': '현재 비밀번호가 올바르지 않습니다.'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            validate_password(new_password, user=request.user)
        except DjangoValidationError as e:
            return Response({'detail': e.messages}, status=status.HTTP_400_BAD_REQUEST)

        request.user.set_password(new_password)
        request.user.save(update_fields=['password'])
        return Response({'detail': '비밀번호가 변경되었습니다.'}, status=status.HTTP_200_OK)

@api_view(["GET", "PUT", "PATCH"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def user_profile(request):
    user = request.user
    if request.method == "GET":
        return Response(UserProfileSerializer(user).data)

    ser = UserProfileSerializer(user, data=request.data, partial=True)
    ser.is_valid(raise_exception=True)
    ser.save()
    return Response(ser.data, status=status.HTTP_200_OK)

# ─────────────────────────────────────────────────────────────
# Dashboard (간단 API)
# ─────────────────────────────────────────────────────────────

def _require_login_json(view):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"detail": "Unauthorized"}, status=401)
        return view(request, *args, **kwargs)
    return wrapper

DONE_STATUSES = {"처리완료", "종료"}

@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def dashboard_report_points(request):
    """
    GET /api/dashboard/report-points/?year=2025&animal=고라니
    응답 예:
    [
      {"lat":37.5446,"lng":127.0372,"count":3,"city":"서울","district":"성동구","region":"서울숲","address":"..."},
      ...
    ]
    """
    year   = request.GET.get("year")
    animal = (request.GET.get("animal") or "").strip()
    city   = (request.GET.get("city") or "").strip()
    dist   = (request.GET.get("district") or "").strip()

    qs = (Report.objects
          .select_related("location","animal")
          .exclude(location__isnull=True))

    # 연도 필터
    if year and year.isdigit():
        qs = qs.annotate(y=ExtractYear("report_date")).filter(y=int(year))

    # 동물명(별칭 안전 처리)
    name_field = _animal_name_field(Report)  # 'animal__name_kor' | 'animal__name' | None
    if animal and name_field:
        qs = qs.filter(**{f"{name_field}__iexact": animal})

    # 지역(시/구) 보조 필터
    if city:
        qs = qs.filter(location__city__icontains=city)
    if dist:
        qs = qs.filter(location__district__icontains=dist)

    # 지점(Location)별 카운트
    rows = (qs.values(
                "location_id",
                "location__latitude", "location__longitude",
                "location__city", "location__district",
                "location__region", "location__address",
            )
            .annotate(count=Count("id"))
            .order_by("-count", "location_id"))

    data = []
    for r in rows:
        lat = r["location__latitude"]
        lng = r["location__longitude"]
        if lat is None or lng is None:
            continue
        data.append({
            "lat": float(lat),
            "lng": float(lng),
            "count": r["count"],
            "city": (r["location__city"] or "").strip(),
            "district": (r["location__district"] or "").strip(),
            "region": (r["location__region"] or "").strip(),
            "address": (r["location__address"] or "").strip(),
        })

    return Response(data)


@require_GET
@_require_login_json
def dashboard_reporters(request):
    limit = int(request.GET.get("limit") or 10)
    agg = (
        Report.objects
        .values("user__username")
        .annotate(cnt=Count("id"))
        .order_by("-cnt", "user__username")[:limit]
    )

    data = []
    for row in agg:
        reporter = (row["user__username"] or "(알수없음)")
        data.append({
            "reporter": reporter,  # ✅ 표준 키
            "name": reporter,      # ✅ 임시 호환용(프론트가 r.name을 볼 수도 있으니)
            "count": row["cnt"],
        })

    return JsonResponse({"results": data})

@csrf_exempt
@require_http_methods(["PATCH", "POST"])
@_require_login_json   # ← 이미 대시보드 JSON 엔드포인트에서 쓰던 래퍼 (세션 로그인 확인)  :contentReference[oaicite:0]{index=0}
def dashboard_report_update_status(request, report_id: int):
    """
    PATCH/POST /api/dashboard/reports/<report_id>/status/
    body: { "status": "checking|on_hold|completed", "reply": "선택(알림용)" }
    - 세션 로그인된 관리자만 허용 (원하면 is_admin 체크 추가)
    - 변경 시 개인 알림(개별) upsert
    """
    try:
        rpt: Report = Report.objects.select_related('user').get(id=report_id)
    except Report.DoesNotExist:
        return JsonResponse({"detail": "not found"}, status=404)

    # (선택) 관리자만 허용하려면 여기에 is_admin 검사 추가
    # if not is_admin(request.user): return JsonResponse({"detail": "forbidden"}, status=403)

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        data = {}
    new_status = (data.get("status") or "").strip()
    reply      = data.get("reply")  # 선택값, None 허용

    allowed = {c[0] for c in Report.STATUS_CHOICES}  # checking/on_hold/completed  :contentReference[oaicite:1]{index=1}
    if new_status not in allowed:
        return JsonResponse({"detail": f"status must be one of {sorted(list(allowed))}"}, status=400)

    old_status = rpt.status
    if old_status == new_status:
        return JsonResponse({
            "report_id": rpt.id,
            "status": rpt.status,
            "changed": False
        }, status=200)

    with transaction.atomic():
        rpt.status = new_status
        rpt.save(update_fields=["status"])

        # 상태 변경 시 개인 알림 업서트 (기존 유틸 재사용)  :contentReference[oaicite:2]{index=2}
        admin_obj = getattr(request.user, "admin", None) if is_admin(request.user) else None
        _upsert_notification_for_report(
            report=rpt,
            reply=(reply or None),
            status_change=f"{old_status}->{new_status}",
            admin_obj=admin_obj,
        )

    return JsonResponse({
        "report_id": rpt.id,
        "status": rpt.status,
        "changed": True
    }, status=200)

# 토큰 저장 API
# FCM 등록 토큰은 길고 복잡합니다. 엄격한 정규식은 불필요하게 실패를 유발할 수 있으니
# 1차 방어선으로 "공백 없음 + 최소 길이" 정도만 확인합니다.
FCM_TOKEN_RE = re.compile(r"^[^\s]{20,}$")

class DeviceTokenViewSet(mixins.CreateModelMixin, viewsets.GenericViewSet):
    queryset = DeviceToken.objects.all()
    serializer_class = DeviceTokenSerializer
    permission_classes = [AllowAny]
    authentication_classes = []  # ← 전체 비활성화가 가능하면 이 한 줄로 끝

    # 만약 ViewSet의 다른 액션은 인증이 필요하다면 ↓ 처럼 분기:
    # def get_authenticators(self):
    #     # register_fcm일 때만 인증 안 함
    #     if getattr(self, 'action', None) == 'register_fcm':
    #         return []
    #     return super().get_authenticators()

    @action(detail=False, methods=['post'], url_path='register-fcm', permission_classes=[AllowAny])
    def register_fcm(self, request):
        # (선택) 안전망: 혹시 클라가 만료 토큰을 보내도 무시하고 진행
        auth = get_authorization_header(request)
        if auth:
            request._request.META.pop('HTTP_AUTHORIZATION', None)

        token = (request.data.get('token') or '').strip()
        platform = (request.data.get('platform') or 'android').strip().lower()
        if not token or not FCM_TOKEN_RE.match(token):
            return Response({'detail': 'invalid token'}, status=status.HTTP_400_BAD_REQUEST)

        obj, created = DeviceToken.objects.get_or_create(
            token=token,
            defaults={
                'platform': platform,
                'user': request.user if getattr(request, 'user', None) and request.user.is_authenticated else None,
                'is_active': True,
            },
        )
        if not created:
            dirty = False
            if obj.platform != platform:
                obj.platform = platform; dirty = True
            if not obj.is_active:
                obj.is_active = True; dirty = True
            if dirty:
                obj.save(update_fields=['platform', 'is_active', 'updated_at'])
        ser = DeviceTokenSerializer(obj)
        return Response(ser.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        """
        POST /api/devices/
        멱등성: 동일 token이 이미 있으면 200 + 기존 레코드 반환
        """
        token = (request.data.get("token") or "").strip()
        if token:
            try:
                obj = DeviceToken.objects.get(token=token)
                ser = self.get_serializer(obj)
                return Response(ser.data, status=status.HTTP_200_OK)
            except DeviceToken.DoesNotExist:
                pass
        return super().create(request, *args, **kwargs)

class PushBroadcastView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request):
        title = (request.data.get("title") or "").strip()
        body  = (request.data.get("body")  or "").strip()
        data  = request.data.get("data") or {}
        user_ids = request.data.get("user_ids")

        if not title and not body:
            return Response({"detail": "title 또는 body 중 하나는 필요합니다."}, status=status.HTTP_400_BAD_REQUEST)

        if user_ids is not None and not isinstance(user_ids, list):
            return Response({"detail": "user_ids는 배열이어야 합니다. 예: [1,2,3]"}, status=status.HTTP_400_BAD_REQUEST)
        if isinstance(user_ids, list):
            if len(user_ids) == 0:
                user_ids = None
            else:
                try:
                    user_ids = [int(x) for x in user_ids]
                except (TypeError, ValueError):
                    return Response({"detail": "user_ids는 정수 배열이어야 합니다. 예: [1,2,3]"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # ✅ DB 기록 없이 FCM만 전송
            ok, fail = send_push_only(
                title=title or "공지",
                body=body or "",
                data=data,
                user_ids=user_ids,
            )
        except Exception as e:
            return Response({"detail": f"푸시 전송 중 오류가 발생했습니다: {e!s}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"success": ok, "failure": fail}, status=status.HTTP_200_OK)

class FCMTestTokenView(APIView):
    permission_classes = [permissions.AllowAny]  # 필요 시 인증으로 변경

    def post(self, request, *args, **kwargs):
        """
        body 예시: {"token":"...", "title":"테스트", "body":"안녕하세요", "dry_run": true}
        """
        token = (request.data.get("token") or "").strip()
        title = request.data.get("title") or "SENCITY 테스트"
        body  = request.data.get("body") or "서버에서 보낸 테스트 알림"
        dry   = bool(request.data.get("dry_run", False))
        data  = request.data.get("data") or {}

        if not token:
            return Response({"detail": "token is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            resp = send_fcm_to_token(token=token, title=title, body=body, data=data, dry_run=dry)
            return Response({"message_id": resp, "dry_run": dry})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class FCMTestTopicView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        """
        body 예시: {"topic":"sencity-test", "title":"테스트", "body":"토픽 발송", "dry_run": true}
        """
        topic = (request.data.get("topic") or "").strip()
        title = request.data.get("title") or "SENCITY 테스트(토픽)"
        body  = (request.data.get("body") or "서버에서 보낸 테스트 알림(토픽)").strip()
        dry   = bool(request.data.get("dry_run", False))
        data  = request.data.get("data") or {}

        if not topic:
            return Response({"detail": "topic is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            resp = send_fcm_to_topic(topic=topic, title=title, body=body, data=data, dry_run=dry)
            return Response({"message_id": resp, "dry_run": dry})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class UpdateReportStatusView(APIView):
    permission_classes = [IsAdminUser]  # 관리자만 변경

    # 허용 상태값(대시보드에서 쓰는 값과 일치시켜 주세요)
    ALLOWED = {"checking", "in_progress", "completed", "on_hold"}

    def patch(self, request, pk: int):
        Report = apps.get_model("dashboard", "Report")  # ← Report는 dashboard 앱에 있음
        try:
            rpt = Report.objects.get(pk=pk)
        except Report.DoesNotExist:
            return Response({"detail": "report not found"}, status=status.HTTP_404_NOT_FOUND)

        new_status = (request.data or {}).get("status", "")
        if new_status not in self.ALLOWED:
            return Response({"detail": "invalid status", "allowed": sorted(self.ALLOWED)},
                            status=status.HTTP_400_BAD_REQUEST)

        rpt.status = new_status
        rpt.save(update_fields=["status"])
        return Response({"ok": True, "id": rpt.id, "status": rpt.status})
