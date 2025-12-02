from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),

    # API
    path('api/', include('api.urls')),

    path("api/ai/", include("api.ai.urls")),

    # Dashboard (namespace 사용 시 dashboard/urls.py에 app_name='dashboard' 필요)
    path('dashboard/', include('dashboard.urls', namespace='dashboard')),

    # JWT
    path('api/auth/jwt/create/',  TokenObtainPairView.as_view(),  name='jwt-create'),
    path('api/auth/jwt/refresh/', TokenRefreshView.as_view(),     name='jwt-refresh'),

    # Django 기본 인증 (login/logout/password_change/…)
    path('accounts/', include('django.contrib.auth.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL,   document_root=settings.MEDIA_ROOT)
