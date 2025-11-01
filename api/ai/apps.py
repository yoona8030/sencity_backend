from django.apps import AppConfig

class AiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api.ai"   # ← 모듈 경로
    label = "ai"      # ← 앱 라벨(선택, 고유하면 됨)
