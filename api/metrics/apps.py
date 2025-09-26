from django.apps import AppConfig

class MetricsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api.metrics"
    label = "metrics"  # (이미 쓰고 있던 값)
    verbose_name = "Sencity Metrics"

    def ready(self):
        from . import signals  # noqa
