# api/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework.routers import SimpleRouter

from . import views
from .views import (
    SignUpView, LoginView, animal_info, proxy_image_view as image_proxy,
    UserViewSet, AnimalViewSet, SearchHistoryViewSet, LocationViewSet,
    ReportViewSet, NotificationViewSet, FeedbackViewSet, StatisticViewSet,
    AdminViewSet, SavedPlaceViewSet,
    MeProfileView, ChangePasswordView, user_profile,
)

router = DefaultRouter()
router = SimpleRouter()
router.register(r'users',           UserViewSet,          basename='user')
router.register(r'animals',         AnimalViewSet,        basename='animal')
router.register(r'search-history',  SearchHistoryViewSet, basename='search-history')
router.register(r'locations',       LocationViewSet,      basename='location')
router.register(r'reports',         ReportViewSet,        basename='report')
router.register(r'notifications',   NotificationViewSet,  basename='notification')
router.register(r'feedbacks',       FeedbackViewSet,      basename='feedback')
router.register(r'statistics',      StatisticViewSet,     basename='statistic')
router.register(r'admin',           AdminViewSet,         basename='admin')
router.register(r'saved-places',    SavedPlaceViewSet,    basename='saved-place')

urlpatterns = [
    path('', include(router.urls)),

    # JWT
    path('auth/jwt/create/',  TokenObtainPairView.as_view()),
    path('auth/jwt/refresh/', TokenRefreshView.as_view()),
    path("api/auth/jwt/refresh/", TokenRefreshView.as_view(), name="jwt-refresh"),

    # Auth
    path('signup/', SignUpView.as_view()),
    path('login/',  LoginView.as_view()),

    # ✅ 프록시 (프론트의 /api/image-proxy/와 매칭)
    path('image-proxy/', image_proxy, name='image-proxy'),

    # 동물 상세
    path('animal-info/', animal_info, name='animal-info'),

    # 통계
    path('reports/stats/animal/',           views.animal_stats),
    path('reports/stats/region-by-animal/', views.region_by_animal_stats),
    path('reports/stats/animal-raw/',       views.animal_stats_raw),

    # 프로필
    path('user/profile/',         MeProfileView.as_view()),
    path('user/change-password/', ChangePasswordView.as_view()),

    path('', include('inquiries.urls')),
]