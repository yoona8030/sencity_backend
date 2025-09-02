# config/urls.py
from django.contrib import admin
from django.urls import path, include
from api.views import proxy_image_view  # 프록시 뷰는 여기서만 노출

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),   # ✅ 중복 include 금지!
    path('dashboard/', include('dashboard.urls')),
]