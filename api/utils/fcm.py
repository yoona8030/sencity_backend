# api/utils/fcm.py
from typing import Dict, Optional
import logging
from firebase_admin import messaging
from django.conf import settings

logger = logging.getLogger(__name__)

def send_fcm_to_token(
    token: str,
    title: str,
    body: str,
    data: Optional[Dict[str, str]] = None,
    dry_run: bool = False,
) -> str:
    """
    단일 디바이스 토큰으로 알림 전송.
    dry_run=True이면 검증만 하고 실제 발송하지 않음.
    """
    if not token:
        raise ValueError("FCM token is required")

    msg = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        data=data or {},
        token=token,
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                channel_id=getattr(settings, "FCM_ANDROID_CHANNEL_ID", None) or "default",
                sound="default",
            ),
        ),
        apns=messaging.APNSConfig(
            headers={"apns-priority": "10"},
            payload=messaging.APNSPayload(
                aps=messaging.Aps(sound="default", content_available=False)
            ),
        ),
    )
    # dry_run 검증 모드로 먼저 시도 가능
    resp = messaging.send(msg, dry_run=dry_run)
    logger.info("FCM send (dry_run=%s) response: %s", dry_run, resp)
    return resp


def send_fcm_to_topic(
    topic: str,
    title: str,
    body: str,
    data: Optional[Dict[str, str]] = None,
    dry_run: bool = False,
) -> str:
    """
    토픽에 구독된 모든 디바이스로 알림 전송.
    """
    if not topic:
        raise ValueError("FCM topic is required")

    msg = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        data=data or {},
        topic=topic,
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                channel_id="sencity_default_channel",
                sound="default",
            ),
        ),
        apns=messaging.APNSConfig(
            headers={"apns-priority": "10"},
            payload=messaging.APNSPayload(
                aps=messaging.Aps(sound="default", content_available=False)
            ),
        ),
    )
    resp = messaging.send(msg, dry_run=dry_run)
    logger.info("FCM topic send (dry_run=%s) response: %s", dry_run, resp)
    return resp
