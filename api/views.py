from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q, Count
from django.http import JsonResponse
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, viewsets, status, permissions
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated, AllowAny, IsAdminUser, IsAuthenticatedOrReadOnly
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.request import Request
from rest_framework.views import APIView
from .utils import is_admin
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import ( User, Animal, SearchHistory, Location, Report, Notification, Feedback, Admin, Statistic, SavedPlace, Profile )
from .serializers import (
    UserSerializer, UserSignUpSerializer,
    AnimalSerializer, SearchHistorySerializer,
    LocationSerializer, ReportSerializer,
    NotificationSerializer, FeedbackSerializer,
    StatisticSerializer, SavedPlaceSerializer, 
    AdminSerializer, ProfileSerializer, 
    UserProfileSerializer
)
from datetime import datetime
from .filters import ReportFilter, NotificationFilter

User = get_user_model()

def is_admin(user) -> bool:
    return bool(
        user and user.is_authenticated and (
            user.is_staff or user.is_superuser or hasattr(user, 'admin')
        )
    )


class IsAdminOrReadGroup(permissions.BasePermission):
    """
    - SAFE_METHODS(GET/HEAD/OPTIONS): 모두 허용
      (단, 개별 레코드 접근은 get_queryset 필터로 안전하게 제한)
    - 쓰기(POST/PUT/PATCH/DELETE): 관리자만 허용
    """
    def has_permission(self, request: Request, view) -> bool:
        if request.method in permissions.SAFE_METHODS:
            return True
        return is_admin(request.user)

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
    # 1) 전체 집계 (동물명 없으면 '미상')
    rows = (
        Report.objects.values('animal__name_kor')
        .annotate(count=Count('id'))
        .order_by('-count')
    )
    full = [
        {'animal': (r['animal__name_kor'] or '미상'), 'count': r['count']}
        for r in rows
    ]
    # 내림차순 정렬
    full.sort(key=lambda x: x['count'], reverse=True)

    # 2) '기타'가 DB에 이미 있다면 분리
    etc_from_db = next((x for x in full if x['animal'] == '기타'), None)
    non_etc = [x for x in full if x['animal'] != '기타']

    # 3) Top4 + 나머지 합산 → '기타'는 항상 마지막
    top4 = non_etc[:4]
    rest = non_etc[4:]
    etc_sum = (etc_from_db['count'] if etc_from_db else 0) + sum(x['count'] for x in rest)

    data = top4 + ([{'animal': '기타', 'count': etc_sum}] if etc_sum > 0 else [])

    # 4) 기타 상세(Top4에서 제외된 원본 목록)
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

# 지역별 + 동물별 신고 건수
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


class IsAuthenticatedOrReadGroup(permissions.BasePermission):
    """
    - /notifications/?type=group → 로그인 안 해도 읽기 허용 (원하면 막아도 됨)
    - 그 외(개인 공지/피드백) → 인증 필요
    """
    def has_permission(self, request: Request, view) -> bool:
        qtype = request.query_params.get("type", "").lower()
        if qtype == "group" and request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated
############################################################3


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
        .prefetch_related('reports', 'reports__user')  # Report에서 Location FK 참조
        .all()
    )
    serializer_class = LocationSerializer
    permission_classes = [AllowAny]

    filter_backends = [DjangoFilterBackend, OrderingFilter, SearchFilter]
    filterset_fields = [
        'reports__id',          # 이 Location을 참조하는 Report id
        'reports__user_id',     # Report를 통해 사용자 필터
        'city',
        'district',
        'region'
    ]
    search_fields = ['region', 'address', 'city', 'district']
    ordering_fields = ['id', 'latitude', 'longitude']
    ordering = ['-id']

class SavedPlaceViewSet(viewsets.ModelViewSet):
    serializer_class = SavedPlaceSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return SavedPlace.objects.select_related('location').all()
        return SavedPlace.objects.select_related('location').filter(user=user)

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
        return qs.filter(user=user)   # 일반 사용자 → 본인 신고만

    # 신고 생성 시 user 자동 연결
    def perform_create(self, serializer):
        # ← 중복 정의 하나만 남깁니다.
        serializer.save(user=self.request.user)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        from_date = request.query_params.get("from")
        to_date   = request.query_params.get("to")

        if from_date and to_date:
            try:
                start = datetime.strptime(from_date, "%Y-%m-%d").date()
                end   = datetime.strptime(to_date,   "%Y-%m-%d").date()

                # report_date 필드 타입에 맞게 선택:
                #  - DateField면 __gte / __lte
                #  - DateTimeField면 __date__gte / __date__lte
                queryset = queryset.filter(
                    report_date__date__gte=start,
                    report_date__date__lte=end
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
        by_region = dict(lqs.values_list('region').annotate(c=Count('id')))

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
                          mixins.CreateModelMixin,   # 생성 가능
                          mixins.RetrieveModelMixin,
                          mixins.UpdateModelMixin,
                          mixins.DestroyModelMixin,
                          viewsets.GenericViewSet):
    """
    Notification CRUD + 그룹 전송 기능
    """
    queryset = Notification.objects.select_related('user', 'admin').all()
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = NotificationFilter
    ordering_fields = ['id', 'created_at']
    ordering = ['-created_at']

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        qtype = (self.request.query_params.get('type') or '').lower().strip()

        if not user.is_authenticated:
            # 로그인 안 된 경우 → 전체 공지만
            qs = qs.filter(type='group')
        elif is_admin(user):
            # 관리자: 제한 없음
            pass
        else:
            # 일반 사용자: group + 본인 individual
            qs = qs.filter(Q(type='group') | Q(type='individual', user=user))

        # ?type=group 또는 ?type=individual 파라미터가 오면 강제 필터링
        if qtype in ('group', 'individual'):
            qs = qs.filter(type=qtype)

        return qs.order_by('-created_at')
        
    def perform_create(self, serializer):
        admin_obj = getattr(self.request.user, 'admin', None) if is_admin(self.request.user) else None
        serializer.save(admin=admin_obj)

    @action(detail=False, methods=['post'], url_path='send-group')
    def send_group(self, request):
        """
        그룹 알림 생성 (특정 유저 목록 or 전체 공지)
        body 예시:
        {
          "user_ids": [12, 34, 56],   # 생략 시 전체 공지
          "status_change": "checking->completed",
          "reply": "공지 내용입니다"
        }
        """
        user_ids = request.data.get('user_ids') or []
        status_change = request.data.get('status_change')
        reply = request.data.get('reply')

        # status_change 또는 reply 둘 중 하나는 반드시 필요
        if not status_change and not reply:
            return Response({'detail': 'status_change 또는 reply 중 하나는 필요합니다.'},
                            status=status.HTTP_400_BAD_REQUEST)

        # status_change 값 검증
        if status_change:
            valid = dict(Notification.STATUS_CHANGE_CHOICES)
            if status_change not in valid:
                return Response({'status_change': f'허용되지 않은 값입니다: {status_change}'},
                                status=status.HTTP_400_BAD_REQUEST)
            
        # 관리자 정보 (예: request.user 가 AdminUser일 경우)
        admin_obj = getattr(request.user, 'admin', None) if is_admin(request.user) else None
        # 또는 JWT claim 에서 admin_id 추출해서 Admin.objects.get(id=...)

        # 전체 공지
        if not user_ids:
            # 전체 공지 → group, user=None
            Notification.objects.create(
                type='group',
                user=None,
                status_change=status_change,
                reply=reply,
                admin=admin_obj
            )
            return Response({'created': 1}, status=status.HTTP_201_CREATED)

        # 특정 사용자 대상 그룹 공지
        users = User.objects.filter(id__in=user_ids)
        to_create = [
            Notification(
                type='individual',
                user=u,
                status_change=status_change,
                reply=reply,
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
    # FK 표준 필터 (?report=, ?user=, ?admin= 로 PK 필터)
    filterset_fields = ['report', 'user', 'admin']
    ordering_fields = ['feedback_datetime', 'feedback_id']
    ordering = ['-feedback_datetime']

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user

        if not is_admin(user):
            qs = qs.filter(user=user)

        # 프론트 호환: ?user_id= 도 지원 (일반 유저는 자기 범위 안에서만)
        user_id = self.request.query_params.get('user_id')
        if user_id:
            qs = qs.filter(user_id=user_id)

        return qs

    def perform_create(self, serializer):
        # 생성 시 작성자(user)는 토큰 주체로 고정
        serializer.save(user=self.request.user)


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
    """
    GET /animal-info/?name={name_kor}
    """
    name = request.GET.get('name')
    try:
        animal = Animal.objects.get(name_kor=name)
        # 로그인된 상태라면 조회할 때마다 히스토리에 저장
        if request.user and request.user.is_authenticated:
            SearchHistory.objects.create(user=request.user, keyword=name)

        return Response({
            "name":        animal.name_kor,
            "english":     animal.name_eng,
            "image_url":   animal.image_url,
            "features":    animal.features,
            "precautions": animal.precautions,
            "description": animal.description,
        })
    except Animal.DoesNotExist:
        return Response(
            {"message": "해당 동물 정보가 없습니다."},
            status=status.HTTP_404_NOT_FOUND
        )
    
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
    permission_classes = [IsAdminUser]  # DRF 기본 관리자 권한


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
    
@api_view(["GET", "PUT", "PATCH"])  # ← PUT 추가
@permission_classes([IsAuthenticated])
def user_profile(request):
    user = request.user
    if request.method == "GET":
        return Response(UserProfileSerializer(user).data)

    print("[user_profile] incoming data:", dict(request.data))  # 디버깅용
    ser = UserProfileSerializer(user, data=request.data, partial=True)  # 부분수정
    ser.is_valid(raise_exception=True)
    ser.save()
    return Response(ser.data, status=status.HTTP_200_OK)
