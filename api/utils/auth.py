# api/utils/auth.py
from typing import Any

def is_admin(user: Any) -> bool:
    """
    관리자 판정 규칙:
    - superuser 또는 staff 이면 관리자
    - 또는 groups에 'admin' / 'superadmin' 포함 시 관리자
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False

    if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
        return True

    try:
        # user.groups.filter(...) 는 인증 User 모델에서만 유효
        return user.groups.filter(name__in=["admin", "superadmin"]).exists()
    except Exception:
        # groups 관계가 없거나 요청 유저가 Anonymous인 경우 등
        return False
