from rest_framework.permissions import BasePermission

class IsOwnerOrStaff(BasePermission):
    def has_object_permission(self, request, view, obj):
        u = request.user
        if not u.is_authenticated:
            return False
        if u.is_staff:
            return True
        inquiry = getattr(obj, 'inquiry', obj)  # Message면 부모 Inquiry로
        return inquiry.user_id == u.id
