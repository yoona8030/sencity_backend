# api/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from . import views
from .views import (
    SignUpView, LoginView, animal_info, proxy_image_view as image_proxy,
    UserViewSet, AnimalViewSet, SearchHistoryViewSet, LocationViewSet,
    ReportViewSet, NotificationViewSet, FeedbackViewSet, StatisticViewSet,
    AdminViewSet, SavedPlaceViewSet,
    MeProfileView, ChangePasswordView, user_profile,
    # ⬇️ 프론트에서 쓰는 단건 API 3종
    ReverseGeocodeView, RecognizeAnimalView, ReportNoAuthView,
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

    path('signup/', SignUpView.as_view()),
    path('login/',  LoginView.as_view()),

    path('image-proxy/', image_proxy, name='image-proxy'),
    path('animal-info/', animal_info, name='animal-info'),

    path('reports/stats/animal/',           views.animal_stats),
    path('reports/stats/region-by-animal/', views.region_by_animal_stats),
    path('reports/stats/animal-raw/',       views.animal_stats_raw),

    path('user/profile/',         MeProfileView.as_view()),
    path('user/change-password/', ChangePasswordView.as_view()),

    path('location/reverse-geocode', ReverseGeocodeView.as_view()),

    # ✅ 인식 엔드포인트: 한 번만! (여기서는 views.RecognizeAnimalView 사용)
    path('ai/recognize', RecognizeAnimalView.as_view(), name='ai-recognize'),

    path('reports/no-auth', ReportNoAuthView.as_view()),

    path('', include('inquiries.urls')),

    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

]
