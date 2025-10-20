# cctv/apps.py
from django.apps import AppConfig
import os, sys, threading, logging

class CctvConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cctv"

    def ready(self):
        # 관리 커맨드에서는 구동하지 않음
        mgmt_cmds = {"migrate","makemigrations","collectstatic","shell",
                     "createsuperuser","startapp","test"}
        if any(cmd in sys.argv for cmd in mgmt_cmds):
            return

        # runserver/daphne 메인 프로세스에서만 1회 구동
        if os.environ.get("RUN_MAIN") != "true" and "daphne" not in " ".join(sys.argv).lower():
            return

        try:
            from .worker import start_all_workers
            threading.Thread(target=start_all_workers, daemon=True).start()
        except Exception as e:
            logging.getLogger(__name__).warning(f"CCTV 워커 시작 실패: {e}")
