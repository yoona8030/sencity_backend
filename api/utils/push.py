# utils/push.py
import hashlib, time
from django.core.cache import cache
from firebase_admin import messaging

def send_push_once(token_list, title, body, data=None):
    """
    같은 내용으로 짧은 시간 내 중복 발송 방지.
    """
    key_seed = f"{title}|{body}|{','.join(sorted(token_list))[:128]}"
    dedup_key = hashlib.sha256(key_seed.encode()).hexdigest()
    if not cache.add(dedup_key, "sent", timeout=60):  # 이미 1분 내 발송됨
        return {"skipped": True}

    message = messaging.MulticastMessage(
        data={"title": title, "body": body, "type": "notice"},
        tokens=token_list,
    )
    return messaging.send_multicast(message)
