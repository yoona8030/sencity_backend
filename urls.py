# sencity_backend/urls.py
from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),

    path('api/', include('api.urls')),

    path('dashboard/', include('dashboard.urls', namespace='dashboard')),

    path('api/auth/jwt/create/',  TokenObtainPairView.as_view(),  name='jwt-create'),
    path('api/auth/jwt/refresh/', TokenRefreshView.as_view(),     name='jwt-refresh'),

    path('accounts/', include('django.contrib.auth.urls')),

    path('cctv/', include('cctv.urls')),
]

if settings.DEBUG:
    urlpatterns += static('static/', document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
