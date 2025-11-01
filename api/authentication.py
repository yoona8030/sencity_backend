from rest_framework_simplejwt.authentication import JWTAuthentication

class CookieJWTAuthentication(JWTAuthentication):
    """
    1순위: Authorization 헤더(Bearer)
    2순위: HttpOnly 쿠키 'access'
    """
    def authenticate(self, request):
        # 1) Authorization 헤더 우선
        header = self.get_header(request)
        if header is not None:
            raw_token = self.get_raw_token(header)
            if raw_token is None:
                return None
            validated_token = self.get_validated_token(raw_token)
            return (self.get_user(validated_token), validated_token)

        # 2) 없으면 쿠키에서 access 읽기
        raw_token = request.COOKIES.get('access')
        if not raw_token:
            return None
        validated_token = self.get_validated_token(raw_token)
        return (self.get_user(validated_token), validated_token)
