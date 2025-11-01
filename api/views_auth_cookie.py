from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions, authentication
from rest_framework_simplejwt.tokens import RefreshToken, AccessToken
from django.contrib.auth import authenticate

from .serializers import DeviceTokenSerializer
from .models import DeviceToken

# 쿠키 공통 옵션
COOKIE_KW = dict(
    httponly=True,          # JS에서 접근 불가 → XSS에 강함
    samesite='Lax',         # 대시보드/관리자 페이지에 적합
    secure=False,           # ⚠️ 운영(HTTPS)에서는 True로 바꾸세요!
)

class CookieLoginView(APIView):
    """
    POST { "email": "...", "password": "..." }
    성공 시 HttpOnly 쿠키(access, refresh) 설정
    """
    authentication_classes = []     # 로그인은 무인증
    permission_classes = []

    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password')
        user = authenticate(request, username=email, password=password)
        if not user:
            return Response({"detail": "Invalid credentials"}, status=401)

        refresh = RefreshToken.for_user(user)
        access = refresh.access_token

        resp = Response({"success": True, "username": user.username, "email": user.email}, status=200)
        # 만료를 명시하고 싶다면 max_age 또는 expires 옵션 추가 가능
        resp.set_cookie('access', str(access), **COOKIE_KW)
        resp.set_cookie('refresh', str(refresh), **COOKIE_KW)
        return resp


class CookieRefreshView(APIView):
    """
    POST (바디 불필요)
    HttpOnly 'refresh' 쿠키를 읽어 새 access 재발급 → 'access' 쿠키 갱신
    """
    authentication_classes = []     # 리프레시는 refresh 쿠키만으로 진행
    permission_classes = []

    def post(self, request):
        raw_refresh = request.COOKIES.get('refresh')
        if not raw_refresh:
            return Response({"detail": "No refresh cookie"}, status=401)
        try:
            rt = RefreshToken(raw_refresh)
            access = rt.access_token
        except Exception:
            return Response({"detail": "Invalid refresh"}, status=401)

        resp = Response({"success": True}, status=200)
        resp.set_cookie('access', str(access), **COOKIE_KW)
        return resp


class CookieLogoutView(APIView):
    """
    POST (바디 불필요)
    access/refresh 쿠키 제거
    """
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [ # 쿠키 또는 헤더 어느 쪽이든 허용
        # 아래 커스텀 인증은 settings에서 전역 지정도 가능하지만, 여기 별도 지정해도 됨
    ]

    def post(self, request):
        resp = Response({"success": True}, status=200)
        resp.delete_cookie('access')
        resp.delete_cookie('refresh')
        return resp

class DeviceTokenRegisterView(APIView):
    """
    POST /api/device-tokens/
    body: { "token": "...", "platform": "android" | "ios" }
    - 비로그인도 허용(원하시면 IsAuthenticated로 바꾸세요)
    - DRF의 SessionAuthentication로 CSRF 걸리지 않도록 인증 비움
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        # ★ 임시 디버그: 들어온 바디/헤더를 서버 콘솔에 찍어 확인
        print("[DEV] /api/device-tokens/ hit",
              "CT=", request.META.get("CONTENT_TYPE"),
              "body=", (request.body or b"")[:120])

        ser = DeviceTokenSerializer(data=request.data, context={"request": request})
        if not ser.is_valid():
            print("[DEV] serializer errors =", ser.errors)  # ★ 실패 원인 바로 확인
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

        obj = ser.save()
        print("[DEV] saved token head =", (obj.token or "")[:24])  # ★ 저장 확인
        return Response({"ok": True, "token": obj.token}, status=status.HTTP_200_OK)


class DeviceTokenDeleteView(APIView):
    """
    DELETE /api/device-tokens/delete/
    body: { "token": "..." }
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def delete(self, request):
        token = (request.data.get("token") or "").strip()
        if not token:
            return Response({"detail": "token required"}, status=400)
        deleted = DeviceToken.objects.filter(token=token).delete()[0]
        return Response({"ok": True, "deleted": deleted}, status=200)
