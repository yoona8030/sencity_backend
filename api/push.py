# 파일: sencity_backend/api/push.py
from __future__ import annotations

from typing import Iterable, Optional, Dict, Any, Tuple, List
from dataclasses import dataclass
import logging

from firebase_admin import messaging
from django.db import transaction, IntegrityError

from .models import (
    DeviceToken,
    Notification,
    User,
    Notice,
    NoticeDelivery,
)

logger = logging.getLogger(__name__)

# 멀티캐스트 전송 시 한 번에 보낼 최대 토큰 수 (FCM 권장 한도 500)
FCM_MULTICAST_LIMIT = 500

# React Native 측에서 생성한 Android 채널 ID와 반드시 동일해야 합니다.
ANDROID_CHANNEL_ID = "default"

# FCM 오류 코드/메시지 중, 불량 토큰 판정 키워드
UNREGISTERED_HINTS = (
    "UNREGISTERED",
    "NOTREGISTERED",
    "INVALID_REGISTRATION",
    "MISMATCH_SENDER_ID",
    "THIRD_PARTY_AUTH_ERROR",
)


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


@dataclass
class _ResponseLike:
    """여러 전송 API 결과를 공통 포맷으로 정규화."""
    success: bool
    exception: Optional[Exception] = None
    message_id: Optional[str] = None


def _is_unregistered_error(exc: Optional[Exception]) -> bool:
    if exc is None:
        return False
    code = getattr(exc, "code", "") or ""
    msg = getattr(exc, "message", "") or repr(exc)
    target = (code + " " + msg).upper()
    return any(h in target for h in UNREGISTERED_HINTS)


def _deactivate_dead_tokens(tokens: List[str]) -> None:
    """죽은 토큰은 삭제 대신 비활성화 권장."""
    if not tokens:
        return
    DeviceToken.objects.filter(token__in=tokens).update(is_active=False)


def _build_android_cfg(collapse_key: Optional[str] = None) -> messaging.AndroidConfig:
    return messaging.AndroidConfig(
        collapse_key=collapse_key or None,
        priority="high",
        notification=messaging.AndroidNotification(channel_id=ANDROID_CHANNEL_ID),
    )


def _send_chunk_with_best_api(
    *,
    tokens: List[str],
    notification: Optional[messaging.Notification],
    data: Dict[str, str],
    android_cfg: Optional[messaging.AndroidConfig],
) -> Tuple[int, int, List[_ResponseLike]]:
    """
    단일 청크 전송.

    새 FCM Admin SDK 권장 흐름:
      1) send_each_for_multicast (멀티캐스트 전용, 동일 payload + 여러 토큰)
      2) 실패 시 send_each (Message 리스트용)
      3) 여전히 실패하면 토큰별 messaging.send() 루프

    반환: (success_count, failure_count, responses_like)
    """
    # 공통 Message 리스트 (send_each 용)
    messages = [
        messaging.Message(
            token=t,
            notification=notification,
            data=data or None,
            android=android_cfg,
        )
        for t in tokens
    ]

    normalized: List[_ResponseLike] = []

    # 1) 가능하면 send_each_for_multicast 사용
    if hasattr(messaging, "send_each_for_multicast"):
        try:
            multicast_msg = messaging.MulticastMessage(
                tokens=tokens,
                notification=notification,
                data=data or None,
                android=android_cfg,
            )
            resp = messaging.send_each_for_multicast(multicast_msg, dry_run=False)
            normalized = [
                _ResponseLike(
                    success=r.success,
                    exception=getattr(r, "exception", None),
                    message_id=getattr(r, "message_id", None),
                )
                for r in resp.responses
            ]
            return resp.success_count, resp.failure_count, normalized
        except Exception as e:
            logger.exception("[FCM] send_each_for_multicast 예외: %s", e)
            # 계속 진행하여 다음 단계 시도

    # 2) send_each (Message 리스트) 사용
    if hasattr(messaging, "send_each"):
        try:
            resp = messaging.send_each(messages, dry_run=False)
            normalized = [
                _ResponseLike(
                    success=r.success,
                    exception=getattr(r, "exception", None),
                    message_id=getattr(r, "message_id", None),
                )
                for r in resp.responses
            ]
            return resp.success_count, resp.failure_count, normalized
        except Exception as e:
            logger.exception("[FCM] send_each 예외: %s", e)
            # 계속 진행하여 최종 폴백

    # 3) 최종 폴백: 단건 send() 루프
    success = 0
    failure = 0
    normalized = []
    for t in tokens:
        try:
            mid = messaging.send(
                messaging.Message(
                    token=t,
                    notification=notification,
                    data=data or None,
                    android=android_cfg,
                ),
                dry_run=False,
            )
            success += 1
            normalized.append(
                _ResponseLike(success=True, exception=None, message_id=mid)
            )
        except Exception as e:
            failure += 1
            normalized.append(
                _ResponseLike(success=False, exception=e, message_id=None)
            )

    return success, failure, normalized


# ---------------------------------------------------------------------
# A. 대시보드 공지 전용
# ---------------------------------------------------------------------
@transaction.atomic
def send_notice_broadcast(notice_id: int) -> Tuple[int, int]:
    """
    대시보드 공지(Notice)를 전체/대상 토큰에 브로드캐스트.
    - 같은 공지 × 같은 토큰은 NoticeDelivery(unique)로 **중복 차단**
    - 실패 토큰은 is_active=False로 비활성화
    - collapse_key = notice-{id} (안드로이드 중복 병합 시도)
    반환: (success_count, failure_count)
    """
    notice = Notice.objects.select_for_update().get(id=notice_id)

    # 1) 활성 토큰 수집
    active_qs = DeviceToken.objects.filter(is_active=True)
    all_tokens = list(
        dict.fromkeys(
            t.strip()
            for t in active_qs.values_list("token", flat=True)
            if isinstance(t, str) and t.strip()
        )
    )
    if not all_tokens:
        return (0, 0)

    # 2) 이미 보낸 토큰 제외
    already = set(
        NoticeDelivery.objects.filter(notice=notice)
        .values_list("device_token__token", flat=True)
    )
    tokens = [t for t in all_tokens if t not in already]
    if not tokens:
        return (0, 0)

    # 3) 메시지 구성
    collapse = f"notice-{notice.id}"
    notif = messaging.Notification(title=notice.title, body=notice.body or "")
    android_cfg = _build_android_cfg(collapse)
    data = _to_str_dict({
        "type": "notice",
        "notice_id": str(notice.id),
        "title": notice.title,
        "body": notice.body or "",
        "collapse_key": collapse,
    })

    result = PushResult()

    # 4) 청크 전송
    for chunk in _chunk(tokens, FCM_MULTICAST_LIMIT):
        try:
            s, f, responses = _send_chunk_with_best_api(
                tokens=chunk,
                notification=notif,
                data=data,
                android_cfg=android_cfg,
            )
            result.add(s, f)

            # 5) 결과 기록 + 죽은 토큰 비활성화
            dead: List[str] = []
            for idx, r in enumerate(responses):
                tok = chunk[idx]
                try:
                    dt = DeviceToken.objects.get(token=tok)
                except DeviceToken.DoesNotExist:
                    continue

                if r.success:
                    try:
                        NoticeDelivery.objects.create(
                            notice=notice,
                            device_token=dt,
                            status="success",
                            fcm_msg_id=r.message_id,
                        )
                    except IntegrityError:
                        pass
                else:
                    exc = r.exception
                    code = getattr(exc, "code", "") or ""
                    msg = getattr(exc, "message", "") or repr(exc)
                    try:
                        NoticeDelivery.objects.create(
                            notice=notice,
                            device_token=dt,
                            status="failure",
                            error_code=code,
                            error_message=msg,
                        )
                    except IntegrityError:
                        pass
                    if _is_unregistered_error(exc):
                        dead.append(tok)

            if dead:
                _deactivate_dead_tokens(dead)

        except Exception as e:
            logger.exception("[NOTICE] chunk send error: %s", e)
            result.add(0, len(chunk))

    logger.info("[NOTICE] done: success=%d, failure=%d", result.success, result.failure)
    return (result.success, result.failure)


# ---------------------------------------------------------------------
# B. 범용 유틸
# ---------------------------------------------------------------------
def send_push_only(
    *,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    user_ids: Optional[Iterable[int]] = None,
) -> Tuple[int, int]:
    """서버 Notification 기록 없이 FCM만 전송"""
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
    - user_ids가 주어지면 개별 알림(Notification type='individual') 벌크 생성
    - user_ids가 없으면 그룹 알림(Notification type='group') 1건 생성
    - 실패 토큰은 is_active=False로 비활성화 (삭제 X)
    - collapse_key = generic-notice
    반환: (success_count, failure_count)
    """
    payload_data = _to_str_dict(data)

    # 1) 대상 토큰 (활성만)
    qs = DeviceToken.objects.filter(is_active=True)
    if user_ids:
        qs = qs.filter(user_id__in=list(user_ids))

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

    # 3) 공통 메시지
    notif = messaging.Notification(title=title or "공지", body=body or "")
    android_cfg = _build_android_cfg(collapse_key="generic-notice")

    result = PushResult()

    # 4) 청크 전송
    for chunk in _chunk(tokens, FCM_MULTICAST_LIMIT):
        try:
            s, f, responses = _send_chunk_with_best_api(
                tokens=chunk,
                notification=notif,
                data=payload_data,
                android_cfg=android_cfg,
            )
            result.add(s, f)

            # 5) 실패 토큰 비활성화
            if f:
                dead: List[str] = []
                for i, r in enumerate(responses):
                    if r.success:
                        continue
                    if _is_unregistered_error(r.exception):
                        dead.append(chunk[i])
                if dead:
                    _deactivate_dead_tokens(dead)

        except Exception as e:
            logger.exception("[FCM] chunk send error: %s", e)
            result.add(0, len(chunk))

    logger.info("[FCM] done: success=%d, failure=%d", result.success, result.failure)
    return (result.success, result.failure)


__all__ = [
    "send_notice_broadcast",
    "send_push_only",
    "send_push_and_record",
    "FCM_MULTICAST_LIMIT",
    "ANDROID_CHANNEL_ID",
]
