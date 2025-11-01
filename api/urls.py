# api/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenVerifyView
from . import views

from api.metrics.views import DashboardSummaryAPI
from .views import (
    SignUpView, LoginView, animal_info, proxy_image_view,
    UserViewSet, AnimalViewSet, SearchHistoryViewSet, LocationViewSet,
    ReportViewSet, NotificationViewSet, FeedbackViewSet, StatisticViewSet,
    AdminViewSet, SavedPlaceViewSet,
    MeProfileView, ChangePasswordView, user_profile,
    ReverseGeocodeView, RecognizeAnimalView, animal_resolve, ReportNoAuthView,
    dashboard_reports, dashboard_report_stats, dashboard_reporters,
    dashboard_report_points, dashboard_report_update_status, DeviceTokenViewSet, PushBroadcastView,
    FCMTestTokenView, FCMTestTopicView, AppBannerViewSet, AppBannerActiveList,
    UpdateReportStatusView
)
from .views_ml import recognize_animal_grouped
from .views_auth_cookie import (
    CookieLoginView,
    CookieRefreshView,
    CookieLogoutView,
    DeviceTokenRegisterView,
    DeviceTokenDeleteView,
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
router.register(r'app-banners',     AppBannerViewSet,     basename='app-banner')

# 중요: 모바일이 호출하는 FCM 엔드포인트를 'devices' 루트로 노출해야
# /api/devices/register-fcm/ 와 /api/devices/send-test/ 가 정확히 매칭됩니다.
router.register(r'devices',         DeviceTokenViewSet,   basename='device')

urlpatterns = [
    # 커스텀 단일 엔드포인트들을 먼저
    path('animals/resolve/', views.animal_resolve, name='animal_resolve'),

    path('signup/', SignUpView.as_view()),
    path('login/',  LoginView.as_view()),

    path('image-proxy/', proxy_image_view, name='image-proxy'),
    path('image-proxy',  proxy_image_view),

    path('animal-info/', animal_info, name='animal-info'),
    path('reports/stats/animal-raw/', views.animal_stats_raw),

    path('user/profile/',         MeProfileView.as_view()),
    path('user/change-password/', ChangePasswordView.as_view()),

    path('location/reverse-geocode/', ReverseGeocodeView.as_view()),

    # AI 인식 엔드포인트
    path('recognize/', RecognizeAnimalView.as_view(), name='api-recognize'),              # 원래 경로
    path('ai/recognize/', RecognizeAnimalView.as_view(), name='recognize'),
    path('ai/recognize',  RecognizeAnimalView.as_view()),
    path('animals/resolve/', animal_resolve, name='api-animal-resolve'),

    # 비회원 신고
    path('reports/no-auth', ReportNoAuthView.as_view()),

    # 문의 모듈
    path('', include('inquiries.urls')),

    # JWT
    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('token/verify/', TokenVerifyView.as_view(), name='token_verify'),
    path('auth/jwt/refresh/', TokenRefreshView.as_view(), name='jwt_refresh_alias'),

    # KPI
    path("metrics/", include("api.metrics.urls")),
    path("metrics/summary/", DashboardSummaryAPI.as_view(), name="metrics-summary"),

    # 대시보드용 (지도 포인트)
    path('dashboard/report-points/', dashboard_report_points),
    path('dashboard/reports/<int:report_id>/status/', dashboard_report_update_status),
    path('dashboard/reports/',       dashboard_reports,       name='dashboard-reports'),
    path('dashboard/report-stats/',  dashboard_report_stats,  name='dashboard-report-stats'),
    path('dashboard/reporters/',     dashboard_reporters,     name='dashboard-reporters'),


    # 대시보드에서 공지/콘텐츠 푸시 보내는 엔드포인트 (관리자 전용)
    # POST /api/push/broadcast/
    # body 예: { "title":"제목", "body":"내용", "data":{"kind":"notice"}, "user_ids":[1,2] }
    path('push/broadcast/', PushBroadcastView.as_view(), name='push-broadcast'),
    path("app-banners/active/", AppBannerActiveList.as_view(), name="app-banner-active"),

    # 마지막에 router (ViewSet 기반 리소스들)
    path('', include(router.urls)),

    # FCM
    path("fcm/test/token/", FCMTestTokenView.as_view(), name="fcm-test-token"),
    path("fcm/test/topic/", FCMTestTopicView.as_view(), name="fcm-test-topic"),

    path("ml/recognize/", recognize_animal_grouped, name="recognize_animal_grouped"),

    # 쿠키 기반 로그인 / 로그아웃 / 토큰 재발급
    path('login/cookie/', CookieLoginView.as_view(), name='cookie-login'),
    path('token/refresh-cookie/', CookieRefreshView.as_view(), name='cookie-refresh'),
    path('logout/cookie/', CookieLogoutView.as_view(), name='cookie-logout'),

    # 디바이스 토큰
    path("device-tokens/",        DeviceTokenRegisterView.as_view()),
    path("device-tokens/delete/", DeviceTokenDeleteView.as_view()),

    path("ai/", include("api.ai.urls")),
    path("reports/<int:pk>/status/", UpdateReportStatusView.as_view()),

]
