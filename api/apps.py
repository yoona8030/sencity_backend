# api/apps.py
from django.apps import AppConfig
from django.conf import settings
import os, sys, logging
import threading
from django.db import connection

logger = logging.getLogger(__name__)

if connection.vendor == 'sqlite':
    with connection.cursor() as cur:
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")

# 중복 초기화 방지용 모듈 전역 플래그 (프로세스 단위)
__CLASSIFIER_LOADED__ = False

def _should_skip_load() -> bool:
    """
    모델 로딩을 건너뛸지 판단:
    - 개발서버 자동리로더의 1차 프로세스 (RUN_MAIN != 'true')
    - 관리 명령어 (migrate, collectstatic, test, shell 등)
    - 환경변수/세팅 플래그로 명시적 비활성화
    - MODEL_DIR 미설정/부재
    """
    # 명시적 비활성화 스위치
    if getattr(settings, "DISABLE_MODEL_LOAD", False):
        return True
    if os.environ.get("DJANGO_SKIP_MODEL_LOAD") == "1":
        return True

    # 개발(runserver) 자동리로더: 1차 프로세스에서는 항상 스킵
    # 운영(uwsgi/gunicorn 등)에서는 RUN_MAIN 미설정이어도 아래 관리 명령어/경로 조건을 통과하면 로드됩니다.
    if os.environ.get("RUN_MAIN") != "true":
        return True

    # 관리 명령어 스킵
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

    # 모델 경로 점검
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
        """
        Django 앱 시작 시 분류기 로드 (비차단/1회 보장).
        """
        from sencity_backend.firebase_init import init_firebase
        try:
            init_firebase()
        except Exception as e:
            logger.warning("[Firebase init] skipped/failed: %s", e)

        global __CLASSIFIER_LOADED__
        if __CLASSIFIER_LOADED__:
            return

        if _should_skip_load():
            return

        # 비차단 백그라운드 웜업
        def _bg_warmup():
            _load_lock = threading.Lock()
            global __CLASSIFIER_LOADED__
            try:
                with _load_lock:
                    if __CLASSIFIER_LOADED__:
                        return
                from sencity_classification_model.django_model_utils import initialize_classifier
                initialize_classifier(settings.MODEL_DIR)  # SavedModel/.keras/.h5 중 가용 파일 사용
                __CLASSIFIER_LOADED__ = True
                logger.info("[ML] Animal classifier loaded (background).")
            except Exception as e:
                # 로드 실패해도 서버는 계속 구동되도록 로그만 남김
                logger.exception("[ML] Failed to load classifier: %s", e)

        threading.Thread(target=_bg_warmup, daemon=True).start()
