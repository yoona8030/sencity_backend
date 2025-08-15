# api/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    SignUpView,
    LoginView,
    animal_info,
    UserViewSet,
    AnimalViewSet,
    SearchHistoryViewSet,
    LocationViewSet,
    ReportViewSet,
    NotificationViewSet,
    FeedbackViewSet,
    StatisticViewSet,
)

router = DefaultRouter()
router.register(r'users',           UserViewSet,           basename='user')
router.register(r'animals',         AnimalViewSet,         basename='animal')
router.register(r'search-history',  SearchHistoryViewSet,  basename='search-history')
router.register(r'locations',       LocationViewSet,       basename='location')
router.register(r'reports',         ReportViewSet,         basename='report')
router.register(r'notifications',   NotificationViewSet,   basename='notification')
router.register(r'feedbacks',       FeedbackViewSet,       basename='feedback')
router.register(r'statistics',      StatisticViewSet,      basename='statistic')

urlpatterns = [
    # REST framework viewsets
    path('', include(router.urls)),

    # custom endpoints
    path('signup/',      SignUpView.as_view(),    name='signup'),
    path('login/',       LoginView.as_view(),     name='login'),
    path('animal-info/', animal_info,             name='animal-info'),
]
