# api/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenVerifyView
from . import views
from .views import (
    SignUpView, LoginView, animal_info, proxy_image_view,
    UserViewSet, AnimalViewSet, SearchHistoryViewSet, LocationViewSet,
    ReportViewSet, NotificationViewSet, FeedbackViewSet, StatisticViewSet,
    AdminViewSet, SavedPlaceViewSet,
    MeProfileView, ChangePasswordView, user_profile,
    ReverseGeocodeView, RecognizeAnimalView, ReportNoAuthView,
    dashboard_report_points
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
    # ✅ 커스텀 단일 엔드포인트들을 먼저!
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
    path('ai/recognize', RecognizeAnimalView.as_view(), name='ai-recognize'),
    path('reports/no-auth', ReportNoAuthView.as_view()),
    path('', include('inquiries.urls')),

    # JWT
    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('token/verify/', TokenVerifyView.as_view(), name='token_verify'),
    path('auth/jwt/refresh/', TokenRefreshView.as_view(), name='jwt_refresh_alias'),

    path("metrics/", include("api.metrics.urls")),  # KPI

    path('dashboard/report-points/', dashboard_report_points), # dashboard

    path('recognize/', RecognizeAnimalView.as_view(), name='recognize-slash'),
    path('recognize',  RecognizeAnimalView.as_view(), name='recognize-noslash'),
    path('ai/recognize/', RecognizeAnimalView.as_view(), name='ai-recognize-slash'),

    # 🔽 마지막에 router
    path('', include(router.urls)),
]
