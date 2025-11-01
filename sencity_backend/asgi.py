# sencity_backend/sencity_backend/asgi.py
import os, logging
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sencity_backend.settings")

# (선택) Firebase 초기화가 필요하면 유지
try:
    from .firebase_init import init_firebase
    init_firebase()
except Exception as e:
    logging.getLogger(__name__).warning(f"ASGI에서 Firebase 초기화 실패: {e}")

# 루트 routing(application)을 그대로 사용
from .routing import application
