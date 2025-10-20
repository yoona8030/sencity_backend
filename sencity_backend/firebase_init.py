# sencity_backend/firebase_init.py
import os
import json
import logging
import threading

import firebase_admin
from firebase_admin import credentials

logger = logging.getLogger(__name__)
_init_lock = threading.Lock()


def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def init_firebase():
    """
    Firebase Admin을 안전하게 '딱 1회' 초기화하고 app 객체를 반환.
    - GOOGLE_APPLICATION_CREDENTIALS 환경변수의 JSON 키 파일을 사용
    - 키 파일 유효성 검사 + project_id 로깅
    """
    # 이미 초기화된 경우: 바로 반환
    if firebase_admin._apps:
        app = firebase_admin.get_app()
        return app

    with _init_lock:
        # 더블 체크(멀티스레드 보호)
        if firebase_admin._apps:
            return firebase_admin.get_app()

        path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not path:
            raise RuntimeError(
                "GOOGLE_APPLICATION_CREDENTIALS 환경변수가 설정되지 않았습니다. "
                "Firebase 서비스계정 키(JSON) 경로를 지정하세요."
            )

        if not os.path.exists(path):
            raise FileNotFoundError(f"Firebase 키 파일이 존재하지 않습니다: {path}")

        if os.path.getsize(path) == 0:
            raise ValueError(f"Firebase 키 파일이 0바이트입니다: {path}")

        # JSON 유효성 사전 검증(오탈자/깨짐 방지) + project_id 로깅
        try:
            key_json = _read_json(path)
        except json.JSONDecodeError as e:
            raise ValueError(f"Firebase 키 파일이 올바른 JSON이 아닙니다: {path} ({e})") from e

        project_id = key_json.get("project_id")
        if not project_id:
            raise ValueError("서비스계정 JSON에 'project_id'가 없습니다. 올바른 키인지 확인하세요.")

        cred = credentials.Certificate(key_json)
        app = firebase_admin.initialize_app(cred)
        logger.info("Firebase Admin 초기화 완료 (project_id=%s, key=%s)", project_id, os.path.basename(path))
        return app


def get_firebase_project_id() -> str | None:
    """
    초기화에 사용된 서비스계정 JSON의 project_id를 반환(가능하면).
    """
    try:
        path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not path or not os.path.exists(path):
            return None
        key_json = _read_json(path)
        return key_json.get("project_id")
    except Exception:
        return None


# 모듈 임포트 시 자동 초기화
# - 개발/단일 프로세스 환경에선 편리합니다.
# - 운영에서 WSGI/ASGI 다중 프로세스 초기화 제어가 필요하면 이 블록을 주석 처리하고,
#   진입점에서 init_firebase()를 한 번만 호출하세요.
try:
    init_firebase()
except Exception as e:
    # 치명적 중단 대신 경고 로깅 (상황에 따라 raise로 바꿔도 됩니다)
    logger.warning("Firebase 초기화 실패: %s", e)
