from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .views import dashboard_reports
from . import ai_views


app_name = "dashboard"

urlpatterns = [
    # 메인 페이지
    path("", views.page_home, name="home"),
    path("cctv/", views.page_cctv, name="cctv"),
    path("reports/", views.page_reports, name="reports"),
    path("analytics/", views.page_analytics, name="analytics"),
    path("notices/", views.page_notices, name="notices"),
    path("users/", views.page_users, name="users"),
    path("settings/", views.page_settings, name="settings"),

    # 콘텐츠 관리
    path("contents/", views.page_contents, name="contents"),
    path("contents/index/", views.page_contents, name="content_index"),
    path("contents/new/", views.page_content_new, name="content_new"),
    path("contents/recent/", views.recent_list, name="content_recent_list"),
    path("contents/recent/partial/", views.recent_list_partial, name="content_recent_partial"),
    path("contents/confirm-delete/<int:pk>/", views.confirm_delete, name="content_confirm_delete"),
    path("contents/close-confirm/<int:pk>/", views.close_confirm, name="content_close_confirm"),
    path("contents/delete/<int:pk>/", views.delete, name="content_delete"),
    path("contents/edit/<int:content_id>/", views.page_content_edit, name="content_edit"),
    path("contents/preview/<slug:template_key>/", views.page_content_preview, name="content_preview"),
    path("contents/app-banner/create/", views.create_app_banner, name="content_create_app_banner"),
    path("contents/banners/active/", views.active_banners_partial, name="content_banners_active"),

    # 띄우기/내리기 + 현재 노출 배너 파셜
    path("contents/<int:pk>/set-live/", views.content_set_live, name="content_set_live"),
    path("contents/<int:pk>/unset-live/", views.content_unset_live, name="content_unset_live"),
    path("contents/appbanner/<int:pk>/unset-live/", views.content_unset_live_appbanner, name="content_unset_live_appbanner"),
    path("contents/banners/active/", views.active_banners_partial, name="active_banners_partial"),
    path("api/app-banners/active/", views.api_active_banners, name="api_active_banners"),

    # CCTV
    path("cctv/stream/", views.cctv_stream, name="cctv_stream"),
    path("api/cctv-devices/", views.cctv_devices_api, name="cctv_devices_api"),
    path("api/cctv-sensors/", views.cctv_sensors_api, name="cctv_sensors_api"),
    path("api/manual-detection/", views.manual_detection_api),

    # 사용자 API (고도화)
    path("api/users/", views.api_users, name="api_users"),  # 목록 + 필터/정렬
    path("api/users/<int:user_id>/", views.api_user_detail, name="api_user_detail"),  # 상세 패널
    path("api/users/bulk/", views.api_users_bulk, name="api_users_bulk"),  # 일괄 작업
    path("api/users/<int:user_id>/toggle-active/", views.api_user_toggle_active, name="api_user_toggle_active"),
    path("api/users/<int:user_id>/set-role/", views.api_user_set_role, name="api_user_set_role"),
    path("api/users/<int:user_id>/resend-verification/", views.api_user_resend_verification, name="api_user_resend_verification"),
    path("api/users/<int:user_id>/logout-all/", views.api_user_logout_all, name="api_user_logout_all"),

    # API
    path("api/issue-token/", views.api_issue_admin_token, name="dashboard-issue-token"),
    path("api/settings/", views.api_settings, name="api_settings"),
    path("api/report-stats/", views.api_report_stats, name="api_report_stats"),
    path("api/reports/", views.api_reports, name="api_reports"),
    path("api/reporters/", views.api_reporters, name="api_reporters"),
    path("api/analytics/", views.api_analytics, name="api_analytics"),
    path("api/analytics/month-breakdown/", views.month_breakdown, name="month_breakdown"),
    path("api/notices/", views.api_notices, name="api_notices"),
    path("api/notices/push/", views.api_notice_push, name="api_notice_push"),
    path("api/push/broadcast/", views.api_push_broadcast, name="api_push_broadcast"),
    path("api/report-points/", views.api_report_points, name="api_report_points"),

    # 로그아웃
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),

    path("api/dashboard/reports/", dashboard_reports, name="dashboard_reports"),

    # AI 모니터 페이지
    path("ai/", views.ai_monitor, name="ai_monitor"),

    # --- YOLO AI 백엔드 제어용 ---
    path("api/ai/start/", ai_views.ai_start, name="ai_start"),
    path("api/ai/stop/", ai_views.ai_stop, name="ai_stop"),
    path("api/ai/status/", ai_views.ai_status, name="ai_status"),
    path("api/cctv-proxy-frame/", views.cctv_proxy_frame, name="cctv_proxy_frame"),
]
