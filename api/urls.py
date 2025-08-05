from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    SearchHistoryViewSet,
    SignUpView,
    LoginView,
    animal_info,
)

router = DefaultRouter()
router.register(r'search-history', SearchHistoryViewSet, basename='search-history')

urlpatterns = [
    # ───────── 검색 기록 CRUD
    # GET, POST  → /search-history/
    # DELETE     → /search-history/{pk}/
    path('', include(router.urls)),

    # ───────── 회원가입, 로그인, 동물 정보
    path('signup/',      SignUpView.as_view(),    name='signup'),
    path('login/',       LoginView.as_view(),     name='login'),
    path('animal-info/', animal_info,             name='animal-info'),
]
