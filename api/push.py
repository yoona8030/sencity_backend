from __future__ import annotations
"""
FCM 브로드캐스트/타겟 푸시 유틸
- firebase_admin.initialize_app(...) 은 프로젝트 초기화 코드에서 1회 수행
- create_server_notification=False 로 호출하면 서버 DB(Notification)에는 기록하지 않음
- FCM Multicast 는 500개 토큰 단위로 청크 전송
"""

from typing import Iterable, Optional, Dict, Any, Tuple, List
from dataclasses import dataclass
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.db import transaction
from firebase_admin import messaging

from .models import DeviceToken, Notification, User

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────────────
# 상수/유틸
# ────────────────────────────────────────────────────────────────────────────────

FCM_MULTICAST_LIMIT = 500  # 권장 멀티캐스트 최대치
ANDROID_CHANNEL_ID = "sencity-general"  # ⚠️ RN 클라이언트의 채널 ID와 반드시 동일

def _to_str_dict(d: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """FCM data payload 는 문자열 dict 이어야 합니다."""
    if not d:
        return {}
    return {str(k): str(v) for k, v in d.items()}

def _chunk(lst: List[str], size: int) -> Iterable[List[str]]:
    for i in range(0, len(lst), size):
        yield lst[i : i + size]

@dataclass
class PushResult:
    success: int = 0
    failure: int = 0

    def add(self, other: "PushResult") -> None:
        self.success += other.success
        self.failure += other.failure

# ────────────────────────────────────────────────────────────────────────────────
# 공개 API
# ────────────────────────────────────────────────────────────────────────────────

def send_push_only(
    *,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    user_ids: Optional[Iterable[int]] = None,
) -> Tuple[int, int]:
    """서버 DB에 아무것도 기록하지 않고 FCM만 전송."""
    return send_push_and_record(
        title=title,
        body=body,
        data=data,
        user_ids=user_ids,
        create_server_notification=False,  # 기록 끔
    )

@transaction.atomic
def send_push_and_record(
    *,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    user_ids: Optional[Iterable[int]] = None,
    create_server_notification: bool = True,
) -> Tuple[int, int]:
    """
    return: (success_count, failure_count)
    """
    payload_data = _to_str_dict(data)

    # 1) 대상 토큰 수집
    if user_ids:
        tokens_qs = DeviceToken.objects.filter(user_id__in=list(user_ids))
    else:
        tokens_qs = DeviceToken.objects.all()

    raw_tokens = list(tokens_qs.values_list("token", flat=True))
    tokens = [t.strip() for t in raw_tokens if t and t.strip()]
    # 중복 제거(순서 유지)
    tokens = list(dict.fromkeys(tokens))

    # 2) (옵션) 서버 알림 기록
    if create_server_notification:
        if user_ids:
            target_users = User.objects.filter(id__in=list(user_ids))
            to_create: List[Notification] = [
                Notification(
                    type="individual",
                    user=u,
                    reply=body or title or "공지",
                    status_change=None,
                    admin=None,
                    report=None,
                )
                for u in target_users
            ]
            if to_create:
                Notification.objects.bulk_create(to_create, ignore_conflicts=True)
        else:
            Notification.objects.create(
                type="group",
                user=None,
                reply=body or title or "공지",
                status_change=None,
                admin=None,
                report=None,
            )

    # 3) FCM 전송
    if not tokens:
        logger.warning("[FCM] No tokens collected. (user_ids=%s)", user_ids)
        return (0, 0)

    result = PushResult()

        # 공통 payload
        # 공통 payload
    notification_obj = (
        messaging.Notification(title=title or "공지", body=body or "")
        if (title or body) else None
    )
    android_cfg = messaging.AndroidConfig(
        priority="high",
        notification=messaging.AndroidNotification(channel_id=ANDROID_CHANNEL_ID),
    )

    for chunk in _chunk(tokens, FCM_MULTICAST_LIMIT):
        try:
            # ─────────────────────────────────────────────────────────
            # 1) 최신: send_multicast 사용 가능
            # ─────────────────────────────────────────────────────────
            if hasattr(messaging, "send_multicast") and hasattr(messaging, "MulticastMessage"):
                message = messaging.MulticastMessage(
                    tokens=chunk,
                    notification=notification_obj,
                    data=payload_data,
                    android=android_cfg,
                )
                resp = messaging.send_multicast(message, dry_run=False)
                responses = resp.responses
                succ = resp.success_count
                fail = resp.failure_count

            # ─────────────────────────────────────────────────────────
            # 2) 중간: send_all 사용 가능
            # ─────────────────────────────────────────────────────────
            elif hasattr(messaging, "send_all"):
                messages = [
                    messaging.Message(
                        token=t,
                        notification=notification_obj,
                        data=payload_data,
                        android=android_cfg,
                    )
                    for t in chunk
                ]
                resp = messaging.send_all(messages, dry_run=False)
                responses = resp.responses
                succ = resp.success_count
                fail = resp.failure_count

            # ─────────────────────────────────────────────────────────
            # 3) 구버전 폴백: per-token send() + ThreadPool로 병렬
            # ─────────────────────────────────────────────────────────
            else:
                MAX_WORKERS = 8  # 네트워크/서버 여유에 맞게 조절
                def _send_one(msg):
                    try:
                        messaging.send(msg, dry_run=False)
                        return True, None
                    except Exception as e:
                        return False, e

                messages = [
                    messaging.Message(
                        token=t,
                        notification=notification_obj,
                        data=payload_data,
                        android=android_cfg,
                    )
                    for t in chunk
                ]

                ok = fail = 0
                responses = []
                with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
                    futs = [ex.submit(_send_one, msg) for msg in messages]
                    for i, fut in enumerate(as_completed(futs)):
                        suc, err = fut.result()
                        responses.append(type("R", (), {"success": suc, "exception": err})())
                        if suc:
                            ok += 1
                        else:
                            fail += 1

                succ = ok

            # ─────────────────────────────────────────────────────────
            # 공통 집계/정리
            # ─────────────────────────────────────────────────────────
            result.add(PushResult(success=succ, failure=fail))

            # 실패 사유 로깅 + 무효 토큰 정리
            if fail:
                for i, r in enumerate(responses):
                    if not getattr(r, "success", False):
                        exc = getattr(r, "exception", None)
                        reason = getattr(exc, "message", repr(exc)) if exc else "unknown"
                        logger.warning("[FCM][FAIL] token=%s... reason=%s", (chunk[i] or "")[:16], reason)
                        if reason and any(s in reason for s in ("NotRegistered", "InvalidRegistration")):
                            DeviceToken.objects.filter(token=chunk[i]).delete()

        except Exception as e:
            logger.exception("[FCM] chunk send error: %s", e)
            result.add(PushResult(success=0, failure=len(chunk)))

            result.add(PushResult(success=succ, failure=fail))

            # 실패 사유 로깅 + 무효 토큰 정리
            if fail:
                for i, r in enumerate(responses):
                    if not getattr(r, "success", False):
                        exc = getattr(r, "exception", None)
                        reason = getattr(exc, "message", repr(exc)) if exc else "unknown"
                        logger.warning("[FCM][FAIL] token=%s... reason=%s", (chunk[i] or "")[:16], reason)
                        if reason and any(s in reason for s in ("NotRegistered", "InvalidRegistration")):
                            DeviceToken.objects.filter(token=chunk[i]).delete()

        except Exception as e:
            logger.exception("[FCM] chunk send error: %s", e)
            result.add(PushResult(success=0, failure=len(chunk)))

    logger.info("[FCM] multicast done: success=%d, failure=%d", result.success, result.failure)
    return (result.success, result.failure)
