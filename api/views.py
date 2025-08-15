from django.contrib.auth import get_user_model
from django.db.models import Q, Count
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
        """
        GET /api/reports/stats/animal?start=YYYY-MM-DD&end=YYYY-MM-DD&status=checking
        응답: [{ "animal": "고라니", "count": 123 }, ...]
        """
        qs = self.filter_queryset(self.get_queryset())
        rows = (qs.values('animal__name_kor')
                  .annotate(count=Count('id'))
                  .order_by('-count'))
        data = [{'animal': r['animal__name_kor'] or '미상', 'count': r['count']} for r in rows]
        return Response(data)

    # ===== 지역 × 동물별 신고 건수 (스택 바) =====
    @action(detail=False, methods=['get'], url_path='stats/region-by-animal')
    def stats_region_by_animal(self, request):
        """
        GET /api/reports/stats/region-by-animal?regions=서울,경기&start=YYYY-MM-DD&end=YYYY-MM-DD
        응답: [{ "region": "서울", "animal": "고라니", "count": 10 }, ...]
        """
        qs = self.filter_queryset(self.get_queryset())

        # Location 기반 집계
        lqs = Location.objects.filter(id__in=qs.values('location_id'))

        regions = request.query_params.get('regions')
        if regions:
            want = [s.strip() for s in regions.split(',') if s.strip()]
            if want:
                lqs = lqs.filter(region__in=want)

        rows = (lqs.values('region', 'reports__animal__name_kor')
                    .annotate(count=Count('reports__id'))
                    .order_by('region', '-count'))
        data = [{
            'region': r['region'] or '미상',
            'animal': r['reports__animal__name_kor'] or '미상',
            'count': r['count']
        } for r in rows]
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
