# sencity_backend/wsgi.py
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sencity_backend.settings')

# Firebase 초기화
try:
    from .firebase_init import init_firebase
    init_firebase()
except Exception as e:
    # 서버는 계속 구동, 원인만 로깅
    import logging
    logging.getLogger(__name__).warning(f"WSGI에서 Firebase 초기화 실패: {e}")

application = get_wsgi_application()
