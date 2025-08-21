from django.contrib.auth import get_user_model
from django.db.models import Q, Count
from django.http import JsonResponse
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, viewsets, status
from rest_framework.permissions import IsAuthenticated, AllowAny, IsAdminUser, IsAuthenticatedOrReadOnly
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import ( User, Animal, SearchHistory, Location, Report, Notification, Feedback, Statistic )
from .serializers import (
    UserSerializer, UserSignUpSerializer,
    AnimalSerializer, SearchHistorySerializer,
    LocationSerializer, ReportSerializer,
    NotificationSerializer, FeedbackSerializer,
    StatisticSerializer
)
from datetime import datetime
from .filters import ReportFilter, NotificationFilter

User = get_user_model()

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
    permission_classes     = [IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(user=self.request.user).order_by('-id')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # 로그인된 사용자 자신의 기록만 반환 (최신순)
        return self.queryset.filter(user=self.request.user).order_by('-id')

    def perform_create(self, serializer):
        # 생성 시 user 필드 자동 연결
        serializer.save(user=self.request.user)

def animal_stats(request):
    stats = (
        Report.objects.values("animal__name_kor")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    result = [{"animal": s["animal__name_kor"], "count": s["count"]} for s in stats]
    return JsonResponse(result, safe=False)


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

    def perform_create(self, serializer):
        if self.request.user and self.request.user.is_authenticated:
            serializer.save(user=self.request.user)
        else:
            serializer.save()
    def list(self, request, *args, **kwargs):   # ### 수정됨
        queryset = self.filter_queryset(self.get_queryset())

        from_date = request.query_params.get("from")   # ### 수정됨
        to_date = request.query_params.get("to")       # ### 수정됨

        if from_date and to_date:                      # ### 수정됨
            try:
                start = datetime.strptime(from_date, "%Y-%m-%d").date()
                end = datetime.strptime(to_date, "%Y-%m-%d").date()

                # report_date 이 DateField 라면 __gte/__lte, 
                # DateTimeField 라면 __date__gte/__date__lte 사용
                queryset = queryset.filter(
                    report_date__date__gte=start,      # ### 수정됨
                    report_date__date__lte=end         # ### 수정됨
                )
            except ValueError:
                pass

        page = self.paginate_queryset(queryset)        # ### 수정됨
        if page is not None:                           # ### 수정됨
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)               # ### 수정됨

    # ===== 기존 요약 통계 =====
    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        qs = self.filter_queryset(self.get_queryset())
        total = qs.count()

        by_status = dict(qs.values_list('status').annotate(c=Count('id')))
        by_animal = dict(qs.values_list('animal__name_kor').annotate(c=Count('id')))

        # Location 기반 집계
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

    # ✅ Top4 + 기타
    top4 = rows[:4]
    top_animals = [r['animal__name_kor'] or '미상' for r in top4]
    etc_count = sum(r['count'] for r in rows if (r['animal__name_kor'] or '미상') not in top_animals)

    data = [{'animal': r['animal__name_kor'] or '미상', 'count': r['count']} for r in top4]
    if etc_count > 0:
        data.append({'animal': '기타', 'count': etc_count})

    # 👉 프론트에서 legend 색상 순서를 동일하게 쓰기 위해 Top4 + 기타 순서 고정
    return Response({
        "top_animals": top_animals,  # 순서 정보 (예: ["고라니","너구리","멧토끼","여우"])
        "data": data
    })


# ===== 지역 × 동물별 신고 건수 (스택 바) =====
@action(detail=False, methods=['get'], url_path='stats/region-by-animal')
def stats_region_by_animal(self, request):
    """
    GET /api/reports/stats/region-by-animal
    응답: [{ "city": "서울", "animal": "고라니", "count": 10 }, ...]
    """
    qs = self.filter_queryset(self.get_queryset())
    lqs = Location.objects.filter(id__in=qs.values('location_id'))

    rows = (
        lqs.values('city', 'reports__animal__name_kor')
        .annotate(count=Count('reports__id'))
        .order_by('city', '-count')
    )

    # 1️⃣ 도시별 총 count 집계
    city_totals = {}
    for r in rows:
        city = r['city'] or '미상'
        city_totals[city] = city_totals.get(city, 0) + r['count']

    # 2️⃣ 상위 4개 도시 + 기타
    top4_cities = sorted(city_totals.items(), key=lambda x: x[1], reverse=True)[:4]
    top4_names = [r[0] for r in top4_cities]

    data = []
    etc_city_animals = {}  # 기타 도시 → 동물별 합산

    # 3️⃣ 각 도시별 동물 집계
    for city in set(r['city'] or '미상' for r in rows):
        city_rows = [r for r in rows if (r['city'] or '미상') == city]

        # 동물별 합산
        animal_counts = {}
        for r in city_rows:
            animal = r['reports__animal__name_kor'] or '미상'
            animal_counts[animal] = animal_counts.get(animal, 0) + r['count']

        # 동물 Top4 + 기타
        sorted_animals = sorted(animal_counts.items(), key=lambda x: x[1], reverse=True)
        top4_animals = sorted_animals[:4]
        other_animals = sorted_animals[4:]
        etc_animal_count = sum(v for _, v in other_animals)

        final_animals = top4_animals[:]
        if etc_animal_count > 0:
            final_animals.append(("기타", etc_animal_count))

        # 도시 Top4 + 기타 분류
        if city in top4_names:
            for animal, cnt in final_animals:
                data.append({
                    "city": city,
                    "animal": animal,
                    "count": cnt
                })
        else:
            for animal, cnt in final_animals:
                etc_city_animals[animal] = etc_city_animals.get(animal, 0) + cnt

    # 4️⃣ 기타 도시 합산
    for animal, cnt in etc_city_animals.items():
        data.append({
            "city": "기타",
            "animal": animal,
            "count": cnt
        })

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
    queryset = Notification.objects.select_related('user').all()
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = NotificationFilter
    ordering_fields = ['id', 'created_at']
    ordering = ['-created_at']

    @action(detail=False, methods=['post'], url_path='send-group')
    def send_group(self, request):
        """
        그룹 알림 다건 생성
        body 예시:
        {
          "user_ids": [12, 34, 56],
          "status_change": "checking->completed",  # 또는
          "reply": "공지 내용입니다"
        }
        """
        user_ids = request.data.get('user_ids') or []
        if not isinstance(user_ids, list) or not user_ids:
            return Response({'detail': 'user_ids는 비어 있지 않은 리스트여야 합니다.'},
                            status=status.HTTP_400_BAD_REQUEST)

        status_change = request.data.get('status_change')
        reply = request.data.get('reply')
        created_at   = request.data.get('created_at')

        # status_change 또는 reply 둘 중 하나는 반드시 있어야 함
        if not status_change and not reply:
            return Response({'detail': 'status_change 또는 reply 중 하나는 필요합니다.'},
                            status=status.HTTP_400_BAD_REQUEST)

        # status_change 값 검증
        if status_change and status_change not in dict(Notification.STATUS_CHANGE_CHOICES):
            return Response({'status_change': f"허용되지 않은 값입니다: {status_change}"},
                            status=status.HTTP_400_BAD_REQUEST)

        User = Notification._meta.apps.get_model('api', 'User')
        users = User.objects.filter(id__in=user_ids)

        to_create = []
        for u in users:
            to_create.append(Notification(
                user=u,
                type='group',
                status_change=status_change,
                reply=reply,
                created_at=created_at if created_at else None
            ))
        Notification.objects.bulk_create(to_create)

        return Response({'created': len(to_create)}, status=status.HTTP_201_CREATED)
    
class FeedbackViewSet(viewsets.ModelViewSet):
    """
    피드백 조회/등록 (관리자 혹은 신고자)
    """
    queryset = Feedback.objects.select_related('report', 'user', 'admin').all()
    serializer_class = FeedbackSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes     = [IsAuthenticated]

    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['report_id', 'user_id', 'admin_id']
    ordering_fields = ['feedback_datetime', 'feedback_id']
    ordering = ['-feedback_datetime']

    # def get_queryset(self):
    #     qs = Feedback.objects.all().order_by('-feedback_datetime')
    #     # non-staff: own feedback only
    #     if not self.request.user.is_staff:
    #         qs = qs.filter(user=self.request.user)
    #     return qs

    # def perform_create(self, serializer):
    #     serializer.save(user=self.request.user)


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
