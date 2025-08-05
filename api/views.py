from django.contrib.auth import get_user_model
from rest_framework import mixins, viewsets, status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import Animal, SearchHistory
from .serializers import (
    SearchHistorySerializer,
    UserSignUpSerializer,
    UserSerializer,
)

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
