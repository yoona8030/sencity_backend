# cctv/apps.py
from __future__ import annotations

import logging
from django.apps import AppConfig

logger = logging.getLogger(__name__)


class CctvConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cctv"

    def ready(self):
        logger.info("[CCTV] worker auto-start disabled (YOLO removed).")
        return
