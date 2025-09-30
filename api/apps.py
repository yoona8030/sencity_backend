# api/apps.py
from django.apps import AppConfig
from django.conf import settings
import os
import sys

# 중복 초기화 방지용 모듈 전역 플래그 (프로세스 단위)
__CLASSIFIER_LOADED__ = False

class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api"

    def ready(self):
        """
        Django 앱 시작 시 분류기 1회 로드.
        - settings.MODEL_DIR 이 존재할 때만 시도
        - 마이그레이션/수집/테스트 단계에서는 건너뜀
        - 예외 발생하더라도 서버 부팅은 계속되게 로그만 출력
        """
        # 개발 서버 자동리로더(2회 호출) 방지
        if os.environ.get("RUN_MAIN") == "false":
            return

        global __CLASSIFIER_LOADED__
        if __CLASSIFIER_LOADED__:
            return

        # manage.py 커맨드에 따라 스킵
        mgmt_cmd = sys.argv[1] if len(sys.argv) > 1 else ""
        skip_cmds = {
            "makemigrations", "migrate", "collectstatic", "test", "shell",
            "createsuperuser", "changepassword", "dbshell", "loaddata",
            "dumpdata", "check", "showmigrations", "inspectdb",
            "compilemessages", "runserver_plus",
        }
        if mgmt_cmd in skip_cmds:
            print(f"[ML] Skip classifier load during '{mgmt_cmd}'.")
            return

        model_dir = getattr(settings, "MODEL_DIR", None)
        if not model_dir:
            print("[ML] Skip: settings.MODEL_DIR not set.")
            return

        model_dir = str(model_dir)  # Path -> str
        if not os.path.exists(model_dir):
            print(f"[ML] Skip: MODEL_DIR not found: {model_dir}")
            return

        try:
            from sencity_classification_model.django_model_utils import initialize_classifier
            initialize_classifier(model_dir)  # SavedModel/.keras/.h5 중 가용 파일 사용
            __CLASSIFIER_LOADED__ = True
            print("[ML] Animal classifier loaded.")
        except Exception as e:
            print(f"[ML] Failed to load classifier: {e}")
