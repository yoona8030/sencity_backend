# dashboard/urls.py
from django.urls import path
from . import views

app_name = "dashboard"  # ← 사이드바의 {% url 'dashboard:...' %}와 매칭

urlpatterns = [
    # 페이지
    path("", views.page_home, name="home"),
    path("cctv/", views.page_cctv, name="cctv"),
    path("reports/", views.page_reports, name="reports"),
    path("analytics/", views.page_analytics, name="analytics"),
    path("contents/", views.page_contents, name="contents"),
    path("contents/new/", views.page_content_new, name="content_new"),
    path("contents/edit/<int:content_id>/", views.page_content_edit, name="content_edit"),
    path("contents/preview/<slug:template_key>/", views.page_content_preview, name="content_preview"),
    path("notices/", views.page_notices, name="notices"),
    path("users/", views.page_users, name="users"),
    path("settings/", views.page_settings, name="settings"),

    # CCTV 스트림 (← 이 줄이 핵심)
    path("cctv/stream/", views.cctv_stream, name="cctv_stream"),

    # 설정 API
    path("api/settings/", views.api_settings, name="api_settings"),

    # 신고 데이터 API (템플릿 JS에서 호출하는 정확한 경로)
    path("api/report-stats/", views.api_report_stats, name="api_report_stats"),
    path("api/reports/", views.api_reports, name="api_reports"),
    path("api/reporters/", views.api_reporters, name="api_reporters"),

    # 사용자 API
    path("api/users/", views.api_users, name="api_users"),

    # 통계 API
    path("api/analytics/", views.api_analytics, name="api_analytics"),
    path("api/analytics/month-breakdown/", views.month_breakdown, name="month_breakdown"),

    # 공지 API
    path("api/notices/", views.api_notices, name="api_notices")
]
