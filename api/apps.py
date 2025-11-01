# api/apps.py
from django.apps import AppConfig
from django.conf import settings
import os, sys, logging, threading
from django.db import connection

logger = logging.getLogger(__name__)

# 프로세스 단위 중복 로드 방지 플래그
__CLASSIFIER_LOADED__ = False

def _should_skip_load() -> bool:
    """분류기 로드를 건너뛸지 판단"""
    if getattr(settings, "DISABLE_MODEL_LOAD", False):
        return True
    if os.environ.get("DJANGO_SKIP_MODEL_LOAD") == "1":
        return True

    # 개발 runserver 자동 리로더의 1차 프로세스는 스킵
    if os.environ.get("RUN_MAIN") != "true":
        return True

    # 관리 명령어에서는 스킵
    mgmt_cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    skip_cmds = {
        "makemigrations", "migrate", "collectstatic", "test", "shell",
        "createsuperuser", "changepassword", "dbshell", "loaddata",
        "dumpdata", "check", "showmigrations", "inspectdb",
        "compilemessages", "runserver_plus",
    }
    if mgmt_cmd in skip_cmds:
        logger.info("[ML] Skip classifier load during '%s'.", mgmt_cmd)
        return True

    model_dir = getattr(settings, "MODEL_DIR", None)
    if not model_dir:
        logger.info("[ML] Skip: settings.MODEL_DIR not set.")
        return True
    if not os.path.exists(str(model_dir)):
        logger.info("[ML] Skip: MODEL_DIR not found: %s", model_dir)
        return True

    return False


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api"

    def ready(self):
        """앱 시작 시 초기화 작업"""
        # 1) Firebase 초기화 (idempotent)
        try:
            from sencity_backend.firebase_init import init_firebase
            init_firebase()  # 내부에서 firebase_admin._apps 체크
        except Exception as e:
            logger.warning("[Firebase init] skipped/failed: %s", e)

        # 2) SQLite PRAGMA (있을 때만)
        try:
            if connection.vendor == 'sqlite':
                with connection.cursor() as cur:
                    cur.execute("PRAGMA journal_mode=WAL;")
                    cur.execute("PRAGMA synchronous=NORMAL;")
        except Exception as e:
            logger.warning("[SQLite PRAGMA] apply failed: %s", e)

        # 3) 분류기 로드 (조건부, 비차단)
        global __CLASSIFIER_LOADED__
        if __CLASSIFIER_LOADED__:
            return
        if _should_skip_load():
            return

        def _bg_warmup():
            global __CLASSIFIER_LOADED__
            try:
                from sencity_classification_model.django_model_utils import initialize_classifier
                initialize_classifier(settings.MODEL_DIR)
                __CLASSIFIER_LOADED__ = True
                logger.info("[ML] Animal classifier loaded (background).")
            except Exception as e:
                logger.exception("[ML] Failed to load classifier: %s", e)

        threading.Thread(target=_bg_warmup, daemon=True).start()
