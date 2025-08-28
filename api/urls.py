# api/urls.py (정리본)
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework.routers import DefaultRouter
from . import views
from .views import (
    SignUpView, LoginView, animal_info,
    UserViewSet, AnimalViewSet, SearchHistoryViewSet, LocationViewSet,
    ReportViewSet, NotificationViewSet, FeedbackViewSet, StatisticViewSet,
    AdminViewSet, SavedPlaceViewSet,
    MeProfileView, ChangePasswordView, user_profile,
)

router = DefaultRouter()
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
    path('auth/jwt/create/',  TokenObtainPairView.as_view(), name='jwt-create'),
    path('auth/jwt/refresh/', TokenRefreshView.as_view(),    name='jwt-refresh'),

    # Auth
    path('signup/', SignUpView.as_view(), name='signup'),
    path('login/',  LoginView.as_view(),  name='login'),

    # 동물 상세
    path('animal-info/', animal_info, name='animal-info'),

    # 통계(함수 기반: 원본 배열만 반환)
    path('reports/stats/animal/',            views.animal_stats,            name='animal-stats'),
    path('reports/stats/region-by-animal/',  views.region_by_animal_stats,  name='region-by-animal-stats'),
    path('reports/stats/animal-raw/', views.animal_stats_raw, name='animal-stats-raw'),

    # 내 프로필/비번 (하나씩만 유지!)
    path('user/profile/',          MeProfileView.as_view(),     name='user-profile'),
    path('user/change-password/',  ChangePasswordView.as_view(), name='user-change-password'),
]
