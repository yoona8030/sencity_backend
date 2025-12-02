# api/ai/apps.py
from django.apps import AppConfig

class AiConfig(AppConfig):
    """
    AI(동물 분류) 앱 설정
    - INSTALLED_APPS 에 'api.ai.apps.AiConfig' 로 등록되어 있을 것
    """
    default_auto_field = "django.db.models.BigAutoField"
    name = "api.ai"   # 모듈 경로
    label = "ai"      # 앱 라벨 (프로젝트 내에서 고유하면 됨)
