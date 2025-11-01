# 파일: sencity_backend/api/push.py
from __future__ import annotations

from typing import Iterable, Optional, Dict, Any, Tuple, List
from dataclasses import dataclass
import logging

from firebase_admin import messaging
# from django.utils import timezone  # 사용하지 않으면 주석/삭제하세요

from .models import DeviceToken, Notification, User

logger = logging.getLogger(__name__)

# 멀티캐스트 전송 시 한 번에 보낼 최대 토큰 수 (FCM 권장 한도 500)
FCM_MULTICAST_LIMIT = 500

# React Native 측에서 생성한 Android 채널 ID와 반드시 동일해야 합니다.
ANDROID_CHANNEL_ID = "default"


def _to_str_dict(d: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """FCM data payload는 문자열 키/값만 허용하므로 강제 변환합니다."""
    return {} if not d else {str(k): str(v) for k, v in d.items()}


def _chunk(lst: List[str], size: int) -> Iterable[List[str]]:
    """리스트를 고정 크기 청크로 나눕니다."""
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


@dataclass
class PushResult:
    success: int = 0
    failure: int = 0

    def add(self, s: int, f: int) -> None:
        self.success += s
        self.failure += f


def send_push_only(
    *,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    user_ids: Optional[Iterable[int]] = None,
) -> Tuple[int, int]:
    """
    서버 Notification 기록 없이 FCM만 전송합니다.
    반환값: (success_count, failure_count)
    """
    return send_push_and_record(
        title=title,
        body=body,
        data=data,
        user_ids=user_ids,
        create_server_notification=False,
    )


def send_push_and_record(
    *,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    user_ids: Optional[Iterable[int]] = None,
    create_server_notification: bool = True,
) -> Tuple[int, int]:
    """
    FCM 전송 + (옵션) 서버 Notification 기록.
    - user_ids가 주어지면 개별 사용자 알림(Notification type='individual')을 벌크 생성
    - user_ids가 없으면 그룹 알림(Notification type='group') 1건 생성
    - FCM 전송 실패 중 Unregistered/NotRegistered/InvalidRegistration 토큰은 DB에서 삭제
    반환값: (success_count, failure_count)
    """
    payload_data = _to_str_dict(data)

    # 1) 대상 토큰 수집
    qs = DeviceToken.objects.all()
    if user_ids:
        qs = qs.filter(user_id__in=list(user_ids))

    # 중복/공백 제거
    tokens = list(
        dict.fromkeys(
            t.strip()
            for t in qs.values_list("token", flat=True)
            if t and isinstance(t, str) and t.strip()
        )
    )
    if not tokens:
        logger.warning("[FCM] no tokens (user_ids=%s)", user_ids)
        return (0, 0)

    # 2) (옵션) 서버 알림 기록
    if create_server_notification:
        if user_ids:
            users = list(User.objects.filter(id__in=list(user_ids)))
            # 동일 레코드가 이미 존재할 수 있는 상황에 대비해 ignore_conflicts 사용
            Notification.objects.bulk_create(
                [
                    Notification(
                        type="individual",
                        user=u,
                        reply=(body or title or "공지"),
                        status_change=None,
                        admin=None,
                        report=None,
                    )
                    for u in users
                ],
                ignore_conflicts=True,
            )
        else:
            Notification.objects.create(
                type="group",
                user=None,
                reply=(body or title or "공지"),
                status_change=None,
                admin=None,
                report=None,
            )

    # 3) 공통 메시지 구성 (notification + data)
    notif = messaging.Notification(title=title or "공지", body=body or "")
    android_cfg = messaging.AndroidConfig(
        priority="high",
        notification=messaging.AndroidNotification(channel_id=ANDROID_CHANNEL_ID),
    )

    result = PushResult()

    # 4) 청크 전송
    for chunk in _chunk(tokens, FCM_MULTICAST_LIMIT):
        try:
            responses = []  # send_multicast 응답 상세
            succ = fail = 0

            if hasattr(messaging, "send_multicast"):
                msg = messaging.MulticastMessage(
                    tokens=chunk,
                    notification=notif,
                    data=payload_data,
                    android=android_cfg,
                )
                resp = messaging.send_multicast(msg, dry_run=False)
                responses = resp.responses
                succ, fail = resp.success_count, resp.failure_count
            else:
                # firebase_admin 구버전 호환
                for t in chunk:
                    try:
                        messaging.send(
                            messaging.Message(
                                token=t,
                                notification=notif,
                                data=payload_data,
                                android=android_cfg,
                            )
                        )
                        succ += 1
                    except Exception as e:
                        # send_multicast와 유사한 형태로 응답 어레이를 맞추기 위한 임시 객체
                        responses.append(
                            type("R", (), {"success": False, "exception": e})()
                        )
                        fail += 1

            result.add(succ, fail)

            # 5) 실패 토큰 정리 (Unregistered/NotRegistered/InvalidRegistration)
            if fail and responses:
                dead_tokens: List[str] = []
                for i, r in enumerate(responses):
                    if getattr(r, "success", False):
                        continue
                    exc = getattr(r, "exception", None)
                    code = getattr(exc, "code", "") or ""
                    msg = getattr(exc, "message", "") or repr(exc)
                    tok = (chunk[i] or "")[:16]
                    logger.warning(
                        "[FCM][FAIL] token=%s... code=%s msg=%s", tok, code, msg
                    )

                    code_u = str(code).upper()
                    # 다양한 버전/필드 케이스에 대비해 code/message 모두 검사
                    if any(k in code_u for k in ("UNREGISTERED", "NOTREGISTERED")) or any(
                        k in msg.upper() for k in ("NOTREGISTERED", "INVALID_REGISTRATION")
                    ):
                        dead_tokens.append(chunk[i])

                if dead_tokens:
                    DeviceToken.objects.filter(token__in=dead_tokens).delete()

        except Exception as e:
            logger.exception("[FCM] chunk send error: %s", e)
            # 청크 전체 실패로 간주
            result.add(0, len(chunk))

    logger.info("[FCM] done: success=%d, failure=%d", result.success, result.failure)
    return (result.success, result.failure)


# 외부에서 명시적으로 import할 수 있도록 공개 심볼 지정(선택)
__all__ = [
    "send_push_only",
    "send_push_and_record",
    "FCM_MULTICAST_LIMIT",
    "ANDROID_CHANNEL_ID",
]
