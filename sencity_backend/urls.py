from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # 1) 관리자 화면
    path('admin/', admin.site.urls),

    # 2) REST API 엔드포인트
    path('api/', include('api.urls')),

    # 3) (선택) DRF 브라우저 로그인/로그아웃 뷰
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),

    path('dashboard/', include('dashboard.urls', namespace='dashboard')),
]

# DEBUG=True일 때 static, media 로컬 서빙
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
