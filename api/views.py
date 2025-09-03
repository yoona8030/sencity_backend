import requests, ipaddress, socket
from typing import Optional
from urllib.parse import urlparse, urlencode
from datetime import datetime

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import (
    Case, When, Value, CharField, F, Q, Count, OuterRef, Subquery, DateTimeField
)
from django.http import StreamingHttpResponse, JsonResponse, HttpResponse, HttpResponseBadRequest
from django.views.decorators.http import require_GET
from django.views.decorators.cache import cache_page

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, viewsets, status, permissions
from rest_framework.permissions import IsAuthenticated, AllowAny, IsAdminUser
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.request import Request
from rest_framework.views import APIView
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.authentication import JWTAuthentication

from .utils import is_admin
from .models import (
    User, Animal, SearchHistory, Location, Report, Notification,
    Feedback, Admin, Statistic, SavedPlace, Profile
)
from .serializers import (
    UserSerializer, UserSignUpSerializer,
    AnimalSerializer, SearchHistorySerializer,
    LocationSerializer, ReportSerializer,
    NotificationSerializer, FeedbackSerializer,
    StatisticSerializer, SavedPlaceCreateSerializer, SavedPlaceReadSerializer,
    AdminSerializer, ProfileSerializer,
    UserProfileSerializer
)
from .filters import ReportFilter, NotificationFilter


User = get_user_model()

# ------------------------------------------------------------
# Permissions
# ------------------------------------------------------------
class IsAdminOrReadGroup(permissions.BasePermission):
    """
    SAFE_METHODS:
      - ?type=group 쿼리로 목록 조회 → 비로그인 허용
      - 그 외 SAFE 조회는 로그인 필요
      - 객체 조회 시: group 은 누구나, individual 은 관리자 또는 본인만
    비SAFE(POST/PUT/PATCH/DELETE):
      - 관리자만
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


# 선택적으로 사용: /notifications/?type=group 익명 허용 예시
class IsAuthenticatedOrReadGroup(permissions.BasePermission):
    """
    - /notifications/?type=group → 로그인 안 해도 읽기 허용 (원하면 막아도 됨)
    - 그 외(개인 공지/피드백) → 인증 필요
    """
    def has_permission(self, request: Request, view) -> bool:
        qtype = request.query_params.get("type", "").lower()
        if qtype == "group" and request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated)


# ------------------------------------------------------------
# Utilities for Notification
# ------------------------------------------------------------
def _resolve_admin_from_request_or_feedback(request, fb) -> Optional[Admin]:
    """
    알림의 admin 컬럼 채우기:
    - fb.admin 이 Admin이면 그대로
    - fb.admin 이 User이면 그 User.admin
    - 없으면, 요청 주체가 관리자면 request.user.admin
    - 그래도 없으면 None
    """
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
    보고서 하나당 개인 알림 1건 유지(업서트).
    - 있으면 update(필드 채워지면 덮어쓰기)
    - 없으면 create
    - Notification에 report FK 유무 감지
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


# ------------------------------------------------------------
# Auth
# ------------------------------------------------------------
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
            'token': str(refresh.access_token),
            'refresh': str(refresh),
            'username': user.username,
            'email': user.email,
            'user_id': user.id,
        }, status=status.HTTP_200_OK)


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    """
    관리자 전용: 전체 사용자 조회/상세
    """
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdminUser]


# ------------------------------------------------------------
# Image Proxy (SSRF 보호)
# ------------------------------------------------------------
ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_HOSTS_FOR_PROXY = {
    'i.namu.wiki',
    'encrypted-tbn0.gstatic.com',
    'encrypted-tbn1.gstatic.com',
    'encrypted-tbn2.gstatic.com',
    'encrypted-tbn3.gstatic.com',
}
REQUEST_TIMEOUT = 8  # seconds

def _is_private_host(hostname: str) -> bool:
    try:
        ip = socket.gethostbyname(hostname)
        ip_obj = ipaddress.ip_address(ip)
        return (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_reserved
            or ip_obj.is_multicast
        )
    except Exception:
        # DNS 실패 등은 안전하게 막음
        return True


@require_GET
@cache_page(60 * 60)  # 1 hour
def proxy_image_view(request):
    url = (request.GET.get("url") or "").strip()
    if not url:
        return HttpResponseBadRequest("missing url")

    try:
        p = urlparse(url)
        if p.scheme not in ALLOWED_SCHEMES or not p.hostname:
            return HttpResponseBadRequest("invalid url")
        if _is_private_host(p.hostname):
            return HttpResponseBadRequest("private host")
    except Exception:
        return HttpResponseBadRequest("bad url")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        "Referer": f"{p.scheme}://{p.hostname}/",
    }

    try:
        r = requests.get(url, headers=headers, stream=True, timeout=REQUEST_TIMEOUT)
    except Exception:
        return HttpResponseBadRequest("upstream fetch error")

    if not r.ok:
        return HttpResponse(f"upstream status {r.status_code}", status=r.status_code)

    content_type = r.headers.get("Content-Type", "application/octet-stream")
    resp = StreamingHttpResponse(r.iter_content(chunk_size=8192), content_type=content_type)
    cl = r.headers.get("Content-Length")
    if cl and cl.isdigit():
        resp["Content-Length"] = cl
    resp["Cache-Control"] = "public, max-age=86400"
    return resp


# ------------------------------------------------------------
# Domain APIs
# ------------------------------------------------------------
class SearchHistoryViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet
):
    """
    GET    /search-history/        → 로그인 유저 자신의 검색 기록 조회
    POST   /search-history/        → 로그인 유저 자신의 검색 기록 생성
    DELETE /search-history/{pk}/   → 해당 기록 삭제
    """
    queryset = SearchHistory.objects.all()
    serializer_class = SearchHistorySerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(user=self.request.user).order_by('-id')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


def animal_stats(request):
    rows = (
        Report.objects.values('animal__name_kor')
        .annotate(count=Count('id'))
        .order_by('-count')
    )
    full = [
        {'animal': (r['animal__name_kor'] or '미상'), 'count': r['count']}
        for r in rows
    ]
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
    rows = (
        Report.objects.values('animal__name_kor')
        .annotate(count=Count('id'))
        .order_by('-count')
    )
    data = [{'animal': r['animal__name_kor'] or '미상', 'count': r['count']} for r in rows]
    return Response(data)


def region_by_animal_stats(request):
    stats = (
        Report.objects.values("location__city", "animal__name_kor")
        .annotate(count=Count("id"))
        .order_by("location__city")
    )
    result = [
        {
            "city": s["location__city"],
            "animal": s["animal__name_kor"],
            "count": s["count"],
        }
        for s in stats
    ]
    return JsonResponse(result, safe=False)


class AnimalViewSet(viewsets.ReadOnlyModelViewSet):
    """
    모든 사용자: 동물 목록/상세 조회
    """
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
    """
    위치 목록/상세 조회
    """
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
        # 생성 때만 CreateSerializer, 나머지는 ReadSerializer
        return SavedPlaceCreateSerializer if self.action == 'create' else SavedPlaceReadSerializer

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class ReportViewSet(mixins.ListModelMixin,
                    mixins.CreateModelMixin,
                    mixins.RetrieveModelMixin,
                    mixins.UpdateModelMixin,
                    mixins.DestroyModelMixin,
                    viewsets.GenericViewSet):
    """
    신고 CRUD
    - 일반 사용자: 본인 신고만 조회/수정 가능
    - 관리자: 모든 신고 조회/수정 가능
    """
    queryset = Report.objects.select_related('animal', 'user', 'location').all()
    serializer_class = ReportSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = ReportFilter
    ordering_fields = ['report_date']
    ordering = ['-report_date']

    def get_queryset(self):
        user = self.request.user
        qs = Report.objects.select_related('animal', 'user', 'location')
        if user.is_superuser:
            return qs
        return qs.filter(user=user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        """
        상태 변경 시에도 같은 키(보고서)로 Notification을 '업서트'만 한다.
        → Feedback에서 만든 알림과 절대 중복되지 않음.
        """
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
        queryset = self.filter_queryset(self.get_queryset())

        from_date = request.query_params.get("from")
        to_date   = request.query_params.get("to")

        if from_date and to_date:
            try:
                start = datetime.strptime(from_date, "%Y-%m-%d").date()
                end   = datetime.strptime(to_date,   "%Y-%m-%d").date()
                # report_date 필드 타입에 맞게 자동 선택
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

    # ===== 기존 요약 통계 =====
    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        qs = self.filter_queryset(self.get_queryset())
        total = qs.count()

        by_status = dict(qs.values_list('status').annotate(c=Count('id')))
        by_animal = dict(qs.values_list('animal__name_kor').annotate(c=Count('id')))

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

        data = {
            'total': total,
            'by_status': by_status,
            'by_animal': by_animal,
            'by_region': by_region,
        }
        return Response(data)

    # ===== 동물별 신고 건수 (도넛) =====
    @action(detail=False, methods=['get'], url_path='stats/animal')
    def stats_animal(self, request):
        qs = self.filter_queryset(self.get_queryset())
        rows = (
            qs.values('animal__name_kor')
              .annotate(count=Count('id'))
              .order_by('-count')
        )

        top4 = rows[:4]
        top_animals = [r['animal__name_kor'] or '미상' for r in top4]
        etc_count = sum(
            r['count'] for r in rows
            if (r['animal__name_kor'] or '미상') not in top_animals
        )

        data = [
            {'animal': r['animal__name_kor'] or '미상', 'count': r['count']}
            for r in top4
        ]
        if etc_count > 0:
            data.append({'animal': '기타', 'count': etc_count})

        return Response({"top_animals": top_animals, "data": data})

    # ===== 지역 × 동물별 신고 건수 (스택 바) =====
    @action(detail=False, methods=['get'], url_path='stats/region-by-animal')
    def stats_region_by_animal(self, request):
        """
        GET /api/reports/stats/region-by-animal
        응답: [{ "city": "서울", "animal": "고라니", "count": 10 }, ...]
        """
        qs  = self.filter_queryset(self.get_queryset())
        lqs = Location.objects.filter(id__in=qs.values('location_id'))

        rows = (
            lqs.values('city', 'reports__animal__name_kor')
               .annotate(count=Count('reports__id'))
               .order_by('city', '-count')
        )

        city_totals = {}
        for r in rows:
            city = r['city'] or '미상'
            city_totals[city] = city_totals.get(city, 0) + r['count']

        top4_cities = sorted(city_totals.items(), key=lambda x: x[1], reverse=True)[:4]
        top4_names  = [r[0] for r in top4_cities]

        data = []
        etc_city_animals = {}

        for city in set((r['city'] or '미상') for r in rows):
            city_rows = [r for r in rows if (r['city'] or '미상') == city]

            animal_counts = {}
            for r in city_rows:
                animal = r['reports__animal__name_kor'] or '미상'
                animal_counts[animal] = animal_counts.get(animal, 0) + r['count']

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


class NotificationViewSet(mixins.ListModelMixin,
                          mixins.CreateModelMixin,
                          mixins.RetrieveModelMixin,
                          mixins.UpdateModelMixin,
                          mixins.DestroyModelMixin,
                          viewsets.GenericViewSet):
    """
    Notification CRUD + 그룹 전송 기능
    """
    queryset = (Notification.objects
                .select_related('user', 'admin', 'report', 'report__animal', 'report__user')
                .all())
    serializer_class = NotificationSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAdminOrReadGroup]

    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = NotificationFilter
    ordering_fields = ['id', 'created_at']
    ordering = ['-created_at', '-id']

    def get_queryset(self):
        qs = (Notification.objects
              .select_related('user', 'admin', 'report', 'report__animal', 'report__user'))

        qtype = (self.request.query_params.get('type') or '').strip().lower()
        user  = self.request.user

        # ① 그룹 공지: 언제나 group만
        if qtype == 'group':
            return qs.filter(type='group').order_by('-created_at', '-id')

        # ② 개인 알림: 인증 필수 + individual만
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

        # ③ type 누락 시 섞임 방지 → 빈 결과
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
        그룹 공지 생성 (특정 유저 목록 or 전체 공지)
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

        from django.contrib.auth import get_user_model
        UserModel = get_user_model()
        users = UserModel.objects.filter(id__in=user_ids, admin__isnull=True)  # 관리자 계정 제외
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
    """
    피드백 조회/등록 (관리자: 전체 / 일반 사용자: 본인 것만)
    """
    queryset = Feedback.objects.select_related('report', 'user', 'admin').all()
    serializer_class = FeedbackSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['report', 'user', 'admin']  # FK 표준 필터
    ordering_fields = ['feedback_datetime', 'feedback_id']
    ordering = ['-feedback_datetime']

    def get_queryset(self):
        qs = super().get_queryset()
        u = self.request.user

        # 일반 사용자: 내가 신고자(user)인 것만
        if not is_admin(u):
            qs = qs.filter(user_id=u.id)
        else:
            # 관리자: 전체. ?scope=mine → 내가 reporter이거나 내가 속한 admin이 담당인 것
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
                # reply=(fb.content or ""),
                reply=None, 
                status_change=None,
                admin_obj=admin_obj,
            )


def my_notifications_qs(request):
    return (Feedback.objects
            .filter(Q(user_id=request.user.id) | Q(admin__user_id=request.user.id))
            .order_by('-feedback_datetime', '-feedback_id'))


class StatisticViewSet(viewsets.ReadOnlyModelViewSet):
    """
    통계 조회
    """
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

    # features를 리스트로 표준화
    feats = getattr(a, "features", None)
    if isinstance(feats, list):
        features = feats
    elif isinstance(feats, str) and feats.strip():
        features = [s.lstrip('- ').strip() for s in feats.splitlines() if s.strip()]
    else:
        features = []

    # 프록시 이미지 URL 구성
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
    """
    Admin CRUD
    """
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
@permission_classes([IsAuthenticated])
def user_profile(request):
    user = request.user
    if request.method == "GET":
        return Response(UserProfileSerializer(user).data)

    print("[user_profile] incoming data:", dict(request.data))  # 디버깅용
    ser = UserProfileSerializer(user, data=request.data, partial=True)
    ser.is_valid(raise_exception=True)
    ser.save()
    return Response(ser.data, status=status.HTTP_200_OK)
