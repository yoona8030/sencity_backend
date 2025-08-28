# api/utils.py
def is_admin(user):
    """
    User가 Admin OneToOne 관계를 가지고 있으면 True 반환
    """
    return hasattr(user, "admin")
