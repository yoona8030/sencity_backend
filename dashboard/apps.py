from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "dashboard"

    def ready(self):
        from django.contrib.auth.signals import user_logged_in
        from django.dispatch import receiver
        from django.utils import timezone
        from .models import LoginLog
        from django.contrib.auth import get_user_model

        @receiver(user_logged_in)
        def _on_login(sender, request, user, **kwargs):
            try:
                ip = request.META.get("REMOTE_ADDR") or request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or None
                ua = (request.META.get("HTTP_USER_AGENT") or "")[:255]
                LoginLog.objects.create(user=user, ip=ip, user_agent=ua)
            except Exception:
                pass
