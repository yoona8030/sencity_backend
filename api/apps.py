# api/apps.py
from __future__ import annotations

import logging
import os

from django.apps import AppConfig
from django.conf import settings
from django.db.backends.signals import connection_created
from django.dispatch import receiver

# 일부 웹캠/동영상에서 발생하는 블랙 프레임 회피용
os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_MSMF", "1")

logger = logging.getLogger(__name__)


@receiver(connection_created)
def _apply_sqlite_pragmas(sender, connection, **kwargs):
    """
    각 DB 연결이 생성될 때마다 SQLite PRAGMA 적용.
    """
    try:
        if connection.vendor == "sqlite":
            with connection.cursor() as cur:
                cur.execute("PRAGMA journal_mode=WAL;")
                cur.execute("PRAGMA synchronous=NORMAL;")
            logger.info("[SQLite PRAGMA] applied on connection_created.")
    except Exception as e:
        logger.warning("[SQLite PRAGMA] apply failed: %s", e)


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api"

    def ready(self):
        """
        앱 시작 시 초기화 작업.
        - Firebase 초기화만 수행
        - YOLO/구분류기(sencity_classification_model) 워밍업은 더 이상 사용하지 않음
        """
        # 1) Firebase 초기화 (idempotent)
        try:
            from sencity_backend.firebase_init import init_firebase
            init_firebase()
        except Exception as e:
            logger.warning("[Firebase init] skipped/failed: %s", e)
